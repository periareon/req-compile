from __future__ import print_function

import collections
import copy
import itertools
import sys

import six

try:
    from functools32 import lru_cache
except ImportError:
    from functools import lru_cache

from qer import utils
from qer.utils import normalize_project_name, merge_requirements, filter_req, merge_extras


class DependencyNode(object):
    def __init__(self, key, req_name, metadata, extra=None):
        self.key = key
        self.metadata = metadata
        self.req_name = req_name
        self.extra = extra
        self.dependencies = {}  # Dict[DependencyNode, pkg_resources.Requirement]
        self.reverse_deps = set()  # Set[DependencyNode]

    def __repr__(self):
        return self.key

    def __str__(self):
        if self.metadata is None:
            return self.key + ' [UNSOLVED]'
        else:
            return '{}{}=={}'.format(
                self.metadata.name,
                ('[' + self.extra + ']') if self.extra else '',
                self.metadata.version)

    def build_constraints(self):
        req = None
        for node in self.reverse_deps:
            req = merge_requirements(req, node.dependencies[self])

        if req is None:
            if self.metadata is None:
                req = utils.parse_requirement(self.key)
            else:
                req = utils.parse_requirement(self.metadata.name)
            if self.extra:
                req.extras = (self.extra,)
                # Reparse to create a correct hash
                req = utils.parse_requirement(str(req))
        return req


def _build_constraints(root_node, exclude=None):
    constraints = []
    for node in root_node.reverse_deps:
        if node.req_name != exclude:
            req = node.dependencies[root_node]
            specifics = ' (' + str(req.specifier) + ')' if req.specifier else ''
            source = node.metadata.name + ('[' + node.extra + ']' if node.extra else '')
            constraints += [source + specifics]
    return constraints


class DistributionCollection(object):
    def __init__(self):
        self.nodes = {}  # Dict[str, DependencyNode]

    @staticmethod
    def _build_key(name, extra=None):
        return utils.normalize_project_name(name) + (('[' + extra + ']') if extra else '')

    def add_dist(self, metadata, source, reason):
        """
        Add a distribution

        Args:
            metadata (DistInfo, None): Distribution info to add
            source (DependencyNode, None): The source of the distribution, e.g. a filename
            reason (pkg_resources.Requirement, optional):
        """
        if reason is not None and len(reason.extras) > 1:
            for extra in reason.extras:
                new_req = copy.copy(reason)
                new_req.extras = (extra,)
                self.add_dist(metadata, source, new_req)
            return

        has_metadata = False
        if isinstance(metadata, six.string_types):
            req_name = metadata
        else:
            has_metadata = True
            req_name = metadata.name

        extra = reason.extras[0] if reason is not None and reason.extras else None
        key = DistributionCollection._build_key(req_name, extra)

        if key in self.nodes:
            node = self.nodes[key]
        else:
            node = DependencyNode(key, req_name, None, extra)
            self.nodes[key] = node

        if extra:
            # Add a reference back to the root req
            base_node = self.add_base(node, reason, req_name)
        else:
            base_node = node

        nodes = {base_node}
        if has_metadata:
            self.update_dists(base_node, metadata)

            # Apply the same metadata to all extras
            for reverse_node in base_node.reverse_deps:
                if reverse_node.req_name == req_name:
                    self.update_dists(reverse_node, metadata)
                    nodes.add(reverse_node)

        if base_node.metadata is not None and reason is not None:
            if not reason.specifier.contains(base_node.metadata.version):
                # Discard the metadata
                self.remove_dists(base_node, remove_upstream=False)

                for reverse_node in base_node.reverse_deps:
                    if reverse_node.req_name == req_name:
                        self.remove_dists(reverse_node, remove_upstream=False)

        if source is not None:
            node.reverse_deps.add(source)
            source.dependencies[node] = reason

        if not has_metadata:
            return set()
        return nodes

    def add_base(self, node, reason, req_name):
        if reason is not None:
            non_extra_req = copy.copy(reason)
            non_extra_req.extras = ()
            non_extra_req = utils.parse_requirement(str(non_extra_req))
        else:
            non_extra_req = utils.parse_requirement(req_name)

        self.add_dist(req_name, node, non_extra_req)
        return self.nodes[req_name]

    def update_dists(self, node, metadata):
        node.metadata = metadata
        for req in metadata.requires(node.extra):
            # This adds a placeholder entry
            self.add_dist(req.name, node, req)

    def remove_dists(self, node, remove_upstream=True):
        if isinstance(node, collections.Iterable):
            for single_node in node:
                self.remove_dists(single_node)
            return

        if node.key not in self.nodes:
            return

        if remove_upstream:
            del self.nodes[node.key]
            for reverse_dep in node.reverse_deps:
                del reverse_dep.dependencies[node]

        for dep in node.dependencies:
            if remove_upstream or dep.req_name != node.req_name:
                dep.reverse_deps.remove(node)
                if not dep.reverse_deps:
                    self.remove_dists(dep)

        if not remove_upstream:
            node.dependencies = {}
            node.metadata = None

    def build(self, roots):
        results = self.generate_lines(roots)
        return [utils.parse_requirement(result[0]) for result in results]

    def generate_lines(self, roots, req_filter=None, _visited=None):
        """
        Generate the lines of a results file from this collection
        Args:
            roots (list[DependencyNode]): List of roots to generate lines from
            req_filter (Callable): Filter to apply to each element of the collection.
                Return True to keep a node, False to exclude it
            _visited (set): Internal set to make sure each node is only visited once
        Returns:
            (list[str]) List of rendered node entries in the form of
                reqname==version   # reasons
        """
        if _visited is None:
            _visited = set()
        req_filter = req_filter or (lambda _: True)

        results = []
        for node in itertools.chain(*[six.iterkeys(root.dependencies) for root in roots]):
            if node in _visited:
                continue

            _visited.add(node)

            if isinstance(node.metadata, DistInfo) and not node.extra:
                extras = []
                constraints = _build_constraints(node, exclude=node.metadata.name)
                for reverse_dep in node.reverse_deps:
                    if reverse_dep.metadata.name == node.metadata.name:
                        if reverse_dep.extra is None:
                            print('Reverse dep with none extra: {}'.format(reverse_dep))
                        extras.append(reverse_dep.extra)
                        constraints.extend(_build_constraints(reverse_dep))
                try:
                    req_expr = '{}{}=={}'.format(
                        node.metadata.name,
                        ('[' + ','.join(sorted(extras)) + ']') if extras else '',
                        node.metadata.version)
                except TypeError:
                    print('Failed processing {}, extras={}'.format(node, extras),
                          file=sys.stderr)
                    continue

                constraint_text = ', '.join(sorted(constraints))
                if not node.metadata.meta and req_filter(node):
                    results.append((req_expr, constraint_text))

            results.extend(self.generate_lines([node], req_filter=req_filter, _visited=_visited))

        return results

    def __contains__(self, project_name):
        return normalize_project_name(project_name) in self.nodes

    def __iter__(self):
        return iter(self.nodes.values())

    def __getitem__(self, project_name):
        return self.nodes[normalize_project_name(project_name)]


class RequirementsFile(object):
    def __init__(self, filename, reqs):
        self.name = filename
        self.version = utils.parse_version('1')
        self.reqs = list(reqs)
        self.meta = True

    def requires(self, extra=None):
        return [req for req in self.reqs
                if filter_req(req, extra)]


class DistInfo(object):
    def __init__(self, name, version, reqs, meta=False):
        """
        Args:
            name:
            version:
            reqs:
            meta:
        """
        self.key = ''
        self.reqs = list(reqs)
        self.meta = meta
        self._version = version
        self._name = None
        self.name = name
        self._recalc_hash()
        self.source = None

    def __hash__(self):
        return self.hash

    def _recalc_hash(self):
        self.hash = hash(self.key + str(self.version))

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        if value is not None:
            self._name = value
            self.key = utils.normalize_project_name(self._name)
            self._recalc_hash()

    @property
    def version(self):
        return self._version

    @version.setter
    def version(self, value):
        self._version = value
        self._recalc_hash()

    def requires(self, extra=None):
        return [req for req in self.reqs
                if filter_req(req, extra)]

    def __str__(self):
        return '{}=={}'.format(self.name, self.version)

    def __repr__(self):
        return self.name + ' ' + self.version + '\n' + '\n'.join([str(req) for req in self.reqs])
