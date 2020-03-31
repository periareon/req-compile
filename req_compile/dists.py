from __future__ import print_function

import collections
import itertools
import logging
import os
import shutil

import six

from req_compile import utils
from req_compile.utils import (
    normalize_project_name,
    merge_requirements,
    filter_req,
    reduce_requirements,
)


class DependencyNode(object):
    def __init__(self, key, metadata):
        """

        Args:
            key:
            metadata (RequirementContainer):
        """
        self.key = key
        self.metadata = metadata
        self.dependencies = {}  # Dict[DependencyNode, pkg_resources.Requirement]
        self.reverse_deps = set()  # Set[DependencyNode]
        self.repo = None
        self.complete = (
            False  # Whether this node and all of its dependency are completely solved
        )

    def __repr__(self):
        return self.key

    def __str__(self):
        if self.metadata is None:
            return self.key + " [UNSOLVED]"
        if self.metadata.meta:
            return self.metadata.name
        return "==".join(str(x) for x in self.metadata.to_definition(self.extras))

    def __lt__(self, other):
        return self.key < other.key

    @property
    def extras(self):
        extras = set()
        for rdep in self.reverse_deps:
            extras |= set(rdep.dependencies[self].extras)
        return extras

    def add_reason(self, node, reason):
        self.dependencies[node] = reason

    def build_constraints(self):
        result = None

        for rdep_node in self.reverse_deps:
            all_reqs = set(rdep_node.metadata.requires())
            for extra in rdep_node.extras:
                all_reqs |= set(rdep_node.metadata.requires(extra=extra))
            for req in all_reqs:
                if normalize_project_name(req.name) == self.key:
                    result = merge_requirements(result, req)

        if result is None:
            if self.metadata is None:
                result = utils.parse_requirement(self.key)
            else:
                result = utils.parse_requirement(self.metadata.name)
            if self.extras:
                result.extras = self.extras
                # Reparse to create a correct hash
                result = utils.parse_requirement(str(result))
        return result


def _build_constraints(root_node):
    constraints = []
    for node in root_node.reverse_deps:
        all_reqs = set(node.metadata.requires())
        for extra in node.extras:
            all_reqs |= set(node.metadata.requires(extra=extra))
        for req in all_reqs:
            if normalize_project_name(req.name) == root_node.key:
                _process_constraint_req(req, node, constraints)
    return constraints


def _process_constraint_req(req, node, constraints):
    extra = None
    if req.marker:
        for marker in req.marker._markers:  # pylint: disable=protected-access
            if (
                isinstance(marker, tuple)
                and marker[0].value == "extra"
                and marker[1].value == "=="
            ):
                extra = marker[2].value
    source = node.metadata.name + (("[" + extra + "]") if extra else "")
    specifics = " (" + str(req.specifier) + ")" if req.specifier else ""
    constraints.extend([source + specifics])


class DistributionCollection(object):
    def __init__(self):
        self.nodes = {}  # Dict[str, DependencyNode]
        self.logger = logging.getLogger("req_compile.dists")

    @staticmethod
    def _build_key(name):
        return utils.normalize_project_name(name)

    def add_dist(self, name_or_metadata, source, reason):
        """
        Add a distribution

        Args:
            name_or_metadata (RequirementContainer|str): Distribution info to add
            source (DependencyNode, optional): The source of the distribution
            reason (pkg_resources.Requirement, optional):
        """
        self.logger.debug("Adding dist: %s %s %s", name_or_metadata, source, reason)

        if isinstance(name_or_metadata, six.string_types):
            req_name = name_or_metadata
            metadata_to_apply = None
        else:
            metadata_to_apply = name_or_metadata
            req_name = metadata_to_apply.name

        key = DistributionCollection._build_key(req_name)

        if key in self.nodes:
            node = self.nodes[key]
        else:
            node = DependencyNode(key, metadata_to_apply)
            self.nodes[key] = node

        # If a new extra is being supplied, update the metadata
        if (
            reason
            and node.metadata
            and reason.extras
            and set(reason.extras) - node.extras
        ):
            metadata_to_apply = node.metadata

        if source is not None and source.key in self.nodes:
            node.reverse_deps.add(source)
            source.add_reason(node, reason)

        nodes = set()
        if metadata_to_apply is not None:
            nodes |= self._update_dists(node, metadata_to_apply)

        self._discard_metadata_if_necessary(node, reason)

        if node.key not in self.nodes:
            raise ValueError("The node {} is gone, while adding".format(node.key))

        return nodes

    def _discard_metadata_if_necessary(self, node, reason):
        if node.metadata is not None and not node.metadata.meta and reason is not None:
            if node.metadata.version is not None and not reason.specifier.contains(
                node.metadata.version, prereleases=True
            ):
                self.logger.debug(
                    "Existing solution (%s) invalidated by %s", node.metadata, reason
                )
                # Discard the metadata
                self.remove_dists(node, remove_upstream=False)

    def _update_dists(self, node, metadata):
        node.metadata = metadata
        add_nodes = {node}
        for extra in {None} | node.extras:
            for req in metadata.requires(extra):
                # This adds a placeholder entry
                add_nodes |= self.add_dist(req.name, node, req)
        return add_nodes

    def remove_dists(self, node, remove_upstream=True):
        if isinstance(node, collections.Iterable):
            for single_node in node:
                self.remove_dists(single_node, remove_upstream=remove_upstream)
            return

        self.logger.info("Removing dist(s): %s (upstream = %s)", node, remove_upstream)

        if node.key not in self.nodes:
            self.logger.debug("Node %s was already removed", node.key)
            return

        if remove_upstream:
            del self.nodes[node.key]
            for reverse_dep in node.reverse_deps:
                del reverse_dep.dependencies[node]

        for dep in node.dependencies:
            if remove_upstream or dep.key != node.key:
                dep.reverse_deps.remove(node)
                if not dep.reverse_deps:
                    self.remove_dists(dep)

        if not remove_upstream:
            node.dependencies = {}
            node.metadata = None
            node.complete = False

    def build(self, roots):
        results = self.generate_lines(roots)
        return [
            utils.parse_requirement("==".join([result[0][0], str(result[0][1])]))
            for result in results
        ]

    def visit_nodes(
        self, roots, max_depth=None, reverse=False, _visited=None, _cur_depth=0
    ):
        if _visited is None:
            _visited = set()

        if reverse:
            next_nodes = itertools.chain(*[root.reverse_deps for root in roots])
        else:
            next_nodes = itertools.chain(*[root.dependencies.keys() for root in roots])
        for node in next_nodes:
            if node in _visited:
                continue

            _visited.add(node)
            yield node

            if max_depth is None or _cur_depth < max_depth - 1:
                results = self.visit_nodes(
                    [node],
                    reverse=reverse,
                    max_depth=max_depth,
                    _visited=_visited,
                    _cur_depth=_cur_depth + 1,
                )
                for result in results:
                    yield result

    def generate_lines(self, roots, req_filter=None, _visited=None):
        """
        Generate the lines of a results file from this collection
        Args:
            roots (iterable[DependencyNode]): List of roots to generate lines from
            req_filter (Callable): Filter to apply to each element of the collection.
                Return True to keep a node, False to exclude it
            _visited (set): Internal set to make sure each node is only visited once
        Returns:
            (list[str]) List of rendered node entries in the form of
                reqname==version   # reasons
        """
        req_filter = req_filter or (lambda _: True)
        results = []
        for node in self.visit_nodes(roots):
            if not node.metadata.meta and req_filter(node):
                constraints = _build_constraints(node)
                req_expr = node.metadata.to_definition(node.extras)
                constraint_text = ", ".join(sorted(constraints))
                results.append((req_expr, constraint_text))
        return results

    def __contains__(self, project_name):
        req_name = project_name.split("[")[0]
        return normalize_project_name(req_name) in self.nodes

    def __iter__(self):
        return iter(self.nodes.values())

    def __getitem__(self, project_name):
        req_name = project_name.split("[")[0]
        return self.nodes[normalize_project_name(req_name)]


class RequirementContainer(object):
    """A container for a list of requirements"""

    def __init__(self, name, reqs, meta=False):
        self.name = name
        self.reqs = list(reqs) if reqs else []
        self.origin = None
        self.meta = meta

    def requires(self, extra=None):
        return reduce_requirements(req for req in self.reqs if filter_req(req, extra))

    def to_definition(self, extras):
        raise NotImplementedError()


class RequirementsFile(RequirementContainer):
    """Represents a requirements file - a text file containing a list of requirements"""

    def __init__(self, filename, reqs, **_kwargs):
        super(RequirementsFile, self).__init__(filename, reqs, meta=True)

    def __repr__(self):
        return "RequirementsFile({})".format(self.name)

    @classmethod
    def from_file(cls, full_path, **kwargs):
        """Load requirements from a file and build a RequirementsFile

        Args:
            full_path (str): The path to the file to load

        Keyword Args:
            Additional arguments to forward to the class constructor
        """
        reqs = utils.reqs_from_files([full_path])
        return cls(full_path, reqs, **kwargs)

    def __str__(self):
        return self.name

    def to_definition(self, extras):
        return self.name, None


class DistInfo(RequirementContainer):
    """Metadata describing a distribution of a project"""

    def __init__(self, name, version, reqs, meta=False):
        """
        Args:
            name (str): The project name
            version (pkg_resources.Version): Parsed version of the project
            reqs (Iterable): The list of requirements for the project
            meta (bool): Whether or not hte requirement is a meta-requirement
        """
        super(DistInfo, self).__init__(name, reqs, meta=meta)
        self.version = version
        self.source = None

    def __str__(self):
        return "{}=={}".format(*self.to_definition(None))

    def to_definition(self, extras):
        req_expr = "{}{}".format(
            self.name, ("[" + ",".join(sorted(extras)) + "]") if extras else ""
        )
        return req_expr, self.version

    def __repr__(self):
        return (
            self.name
            + " "
            + str(self.version)
            + "\n"
            + "\n".join([str(req) for req in self.reqs])
        )


class PkgResourcesDistInfo(RequirementContainer):
    def __init__(self, dist):
        """
        Args:
            dist (pkg_resources.Distribution): The distribution to wrap
        """
        super(PkgResourcesDistInfo, self).__init__(dist.project_name, None)
        self.dist = dist
        self.version = dist.parsed_version

    def __str__(self):
        return "{}=={}".format(*self.to_definition(None))

    def requires(self, extra=None):
        return self.dist.requires(extras=(extra,) if extra else ())

    def to_definition(self, extras):
        req_expr = "{}{}".format(
            self.dist.project_name,
            ("[" + ",".join(sorted(extras)) + "]") if extras else "",
        )
        return req_expr, self.version

    def __del__(self):
        try:
            shutil.rmtree(os.path.join(self.dist.location, ".."))
        except EnvironmentError:
            pass
