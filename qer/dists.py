import collections

import six

try:
    from functools32 import lru_cache
except ImportError:
    from functools import lru_cache

from qer import utils
from qer.utils import normalize_project_name, merge_requirements, filter_req, merge_extras


class DistributionCollection(object):
    CONSTRAINTS_ENTRY = '#constraints#'

    def __init__(self, constraints=None):
        self.dists = {}
        constraints_dist = DistInfo('#constraints#', 1, constraints or [])
        self.constraints_dist = constraints_dist
        self.dists[DistributionCollection.CONSTRAINTS_ENTRY] = MetadataSources(
            constraints_dist, DistributionCollection.CONSTRAINTS_ENTRY)
        self.orig_roots = None
        self.constraint_cache = collections.defaultdict(dict)

    def add_dist(self, metadata, source):
        """
        Add a distribution

        Args:
            metadata (DistInfo): Distribution info to add
            source (str): The source of the distribution, e.g. a filename
        """
        if metadata.name in self.dists:
            result = self.dists[normalize_project_name(metadata.name)]
            result.add(source, metadata)
        else:
            result = MetadataSources(metadata, source)
            self.dists[normalize_project_name(metadata.name)] = result

        for req in metadata.reqs:
            self.constraint_cache.pop(normalize_project_name(req.name), None)
        return result

    def remove_dist(self, name):
        normalized_name = normalize_project_name(name)
        if normalized_name not in self.dists:
            return False

        real_name = self.dists[normalized_name].metadata.name
        reqs = self.dists[normalized_name].metadata.reqs
        del self.dists[normalized_name]
        self.remove_source(real_name)

        for req in reqs:
            self.constraint_cache.pop(normalize_project_name(req.name), None)
        return True

    def remove_source(self, source):
        dists_to_remove = []
        for dist in six.itervalues(self.dists):
            if source in dist.sources:
                dist.remove(source)
                if not dist.sources:
                    dists_to_remove.append(normalize_project_name(dist.metadata.name))

        if dists_to_remove:
            for dist in dists_to_remove:
                self.remove_dist(dist)

    def __contains__(self, item):
        return normalize_project_name(item) in self.dists

    def __iter__(self):
        return iter(self.dists.values())

    def add_global_constraint(self, constraint):
        result = constraint
        to_remove = None
        for req in self.constraints_dist.reqs:
            if constraint.name == req.name:
                to_remove = req
                result = merge_requirements(req, result)
                break

        if to_remove is not None:
            self.constraints_dist.reqs.remove(to_remove)
        self.constraints_dist.reqs.append(result)
        self.constraints_dist.version += 1

    def build_constraints(self, project_name, extras=()):
        project_name = normalize_project_name(project_name)
        if project_name in self.constraint_cache:
            all_constraints = self.constraint_cache[project_name]
            if extras in all_constraints:
                return all_constraints[extras]

        result = self._calc_constraints(project_name, extras)
        self.constraint_cache[project_name][extras] = result
        return result

    def _calc_constraints(self, project_name, extras):
        normalized_name = normalize_project_name(project_name)
        req = None
        for dist in six.itervalues(self.dists):
            for subreq in dist.metadata.requires(extras=extras):
                if normalize_project_name(subreq.name) == normalized_name:
                    req = merge_requirements(req, subreq)
                    break
        return req if req is not None else utils.parse_requirement(normalized_name)

    def reverse_deps(self, project_name):
        reverse_deps = {}
        normalized_name = normalize_project_name(project_name)
        for dist_name, dist in six.iteritems(self.dists):
            for subreq in dist.metadata.requires(dist.metadata.extras):
                if normalize_project_name(subreq.name) == normalized_name:
                    reverse_deps[dist_name] = subreq
                    break
        return reverse_deps


class MetadataSources(object):
    def __init__(self, metadata, source):
        self.metadata = metadata
        self.sources = dict()
        if source is not None:
            self.add(source, metadata)

    def __repr__(self):
        return '{}  # {}'.format(self.metadata, ', '.join(self.sources))

    def add(self, source, metadata):
        self.sources[source] = metadata.extras
        self.metadata.extras = ()
        for extras in self.sources.values():
            self.metadata.update_extras(extras)

    def remove(self, source):
        del self.sources[source]
        self.metadata.extras = ()
        for extras in self.sources.values():
            self.metadata.update_extras(extras)


class DistInfo(object):
    def __init__(self, name, version, reqs, extras=(), meta=False):
        """
        Args:
            name:
            version:
            reqs:
            extras (tuple[str]): Extras that are active in this metadata by default
            meta:
        """
        self._name = name
        self.reqs = list(reqs)
        self.extras = extras
        self.meta = meta
        self._version = version
        self._recalc_hash()
        self.source = None

    def __hash__(self):
        return self.hash

    def _recalc_hash(self):
        name = self._name or ''
        self.hash = hash(name + str(self.version))

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        self._name = value
        self._recalc_hash()

    @property
    def version(self):
        return self._version

    @version.setter
    def version(self, value):
        self._version = value
        self._recalc_hash()

    @lru_cache(maxsize=None)
    def requires(self, extras=()):
        return [req for req in self.reqs
                if filter_req(req, extras)]

    def update_extras(self, extras):
        """
        Args:
            extras (tuple[str]): Extras to add to this metadata
        Return:
            (bool) True if the extras were updated, False otherwise
        """
        result = self.extras != extras
        if result:
            self.extras = merge_extras(self.extras, extras)
        return result

    def __str__(self):
        extras = ''
        if self.extras:
            extras = '[' + ','.join(sorted(self.extras)) + ']'
        return '{}{}=={}'.format(self.name, extras,
                                 self.version)

    def __repr__(self):
        return self.name + ' ' + self.version + '\n' + '\n'.join([str(req) for req in self.reqs])
