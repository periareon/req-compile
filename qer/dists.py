import collections
from typing import Dict, Set
import copy

import pkg_resources
import six

try:
    from functools32 import lru_cache
except ImportError:
    from functools import lru_cache

from qer import utils
from qer.utils import normalize_project_name, merge_requirements, filter_req, merge_extras


class ConstraintViolatedException(Exception):
    """Raised if a dist cannot be added"""
    def __init__(self, node):
        self.node = node


class DependencyNode(object):
    def __init__(self, key, metadata, extra=None):
        self.key = key
        self.metadata = metadata
        self.extra = extra
        self.dependencies = {}  # type: Dict[DependencyNode, pkg_resources.Requirement]
        self.reverse_deps = set()  # type: Set[DependencyNode]

    def __repr__(self):
        return self.key

    def __str__(self):
        if self.metadata is None:
            return self.key
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
            req = utils.parse_requirement(self.metadata.name)
            if self.extra:
                req.extras = (self.extra,)
                # Reparse to create a correct hash
                req = utils.parse_requirement(str(req))
        return req


class DistributionCollection(object):
    def __init__(self):
        self.nodes = {}  # type: Dict[str, DependencyNode]

    @staticmethod
    def _build_key(name, extra=None):
        return utils.normalize_project_name(name) + (('[' + extra + ']') if extra else '')

    def add_dist(self, metadata, source, reason):
        """
        Add a distribution

        Args:
            metadata (DistInfo, None): Distribution info to add
            source (DependencyNode, None): The source of the distribution, e.g. a filename
            reason (pkg_resources.Requirement):
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

        node_metadata = metadata
        if extra:
            node_metadata = DistInfoMirror()

        if key in self.nodes:
            node = self.nodes[key]
            if has_metadata and (node.metadata is None or node.metadata.invalid):
                node.metadata = node_metadata
        else:
            node = DependencyNode(key, node_metadata if has_metadata else None, extra)
            self.nodes[key] = node

        if extra:
            # Add a reference back to the root req
            if reason is not None:
                non_extra_req = copy.copy(reason)
                non_extra_req.extras = ()
                non_extra_req = utils.parse_requirement(str(non_extra_req))
            else:
                non_extra_req = utils.parse_requirement(req_name)
            base_node = self.add_dist(req_name, node, non_extra_req)
            if has_metadata:
                base_node.metadata = metadata

            node_metadata.metadata = base_node.metadata

        if reason is not None and node.metadata is not None and not node.metadata.invalid and not reason.specifier.contains(node.metadata.version):
            # Discard the metadata
            node.metadata.invalid = True
            self.remove_dist(node)
            raise ConstraintViolatedException(node)
        else:
            if has_metadata:
                for req in metadata.requires(node.extra):
                    self.add_dist(req.name, node, req)

            if source is not None:
                node.reverse_deps.add(source)
                if extra:
                    source.dependencies[node] = utils.parse_requirement(req_name)
                else:
                    source.dependencies[node] = reason

        return node

    def remove_dist(self, node):
        if node.key not in self.nodes:
            return

        del self.nodes[node.key]
        for reverse_dep in node.reverse_deps:
            del reverse_dep.dependencies[node]

        for dep in node.dependencies:
            dep.reverse_deps.remove(node)
            if not dep.reverse_deps:
                self.remove_dist(dep)

    def build(self):
        results = []
        for node in self.nodes.values():
            if isinstance(node.metadata, DistInfo) and not node.extra and not node.metadata.invalid:
                extras = []
                for reverse_dep in node.reverse_deps:
                    if reverse_dep.metadata.name == node.metadata.name:
                        extras.append(reverse_dep.extra)
                req_expr = '{}{}=={}'.format(
                    node.metadata.name,
                    ('[' + ','.join(sorted(extras)) + ']') if extras else '',
                    node.metadata.version)
                results.append(utils.parse_requirement(req_expr))
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
        self.invalid = False

    def requires(self, extra=None):
        return self.reqs


class DistInfoMirror(object):
    def __init__(self):
        self.metadata = None

    @property
    def name(self):
        return self.metadata.name

    @property
    def version(self):
        return self.metadata.version

    @property
    def meta(self):
        return self.metadata.meta

    def requires(self, extra=None):
        return self.metadata.requires(extra=extra)

    @property
    def invalid(self):
        return self.metadata.invalid

    @invalid.setter
    def invalid(self, value):
        self.metadata.invalid = value


class DistInfo(object):
    def __init__(self, name, version, reqs, meta=False):
        """
        Args:
            name:
            version:
            reqs:
            extras (tuple[str]): Extras that are active in this metadata by default
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
        self.invalid = False

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
