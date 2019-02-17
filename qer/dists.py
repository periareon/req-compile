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
        constraints_dist = DistInfo('#constraints#', None, constraints or [])
        self.constraints_dist = constraints_dist
        self.dists[DistributionCollection.CONSTRAINTS_ENTRY] = MetadataSources(
            constraints_dist, DistributionCollection.CONSTRAINTS_ENTRY)
        self.orig_roots = None

    def add_dist(self, metadata, source):
        if metadata.name in self.dists:
            self.dists[normalize_project_name(metadata.name)].sources.add(source)
        else:
            self.dists[normalize_project_name(metadata.name)] = MetadataSources(metadata, source)

    def remove_dist(self, name):
        del self.dists[normalize_project_name(name)]

    def remove_source(self, source):
        dists_to_remove = []
        for dist in six.itervalues(self.dists):
            if source in dist.sources:
                dist.sources.remove(source)
                if not dist.sources:
                    dists_to_remove.append(normalize_project_name(dist.metadata.name))

        for dist in dists_to_remove:
            del self.dists[dist]

    def __contains__(self, item):
        return normalize_project_name(item) in self.dists

    def __iter__(self):
        return iter(self.dists.values())

    def add_global_constraint(self, constraint):
        self.constraints_dist.reqs.append(constraint)

    def build_constraints(self, project_name, extras=()):
        normalized_name = normalize_project_name(project_name)
        req = None if normalized_name == DistributionCollection.CONSTRAINTS_ENTRY \
            else utils.parse_requirement(normalized_name)
        for dist_name, dist in six.iteritems(self.dists):
            for subreq in dist.metadata.requires(extras=extras):
                if normalize_project_name(subreq.name) == normalized_name:
                    req = merge_requirements(req, subreq)
                    break
        return req

    def reverse_deps(self, project_name):
        reverse_deps = {}
        normalized_name = normalize_project_name(project_name)
        for dist_name, dist in six.iteritems(self.dists):
            for subreq in dist.metadata.reqs:
                if normalize_project_name(subreq.name) == normalized_name:
                    reverse_deps[dist_name] = subreq
                    break
        return reverse_deps


class MetadataSources(object):
    def __init__(self, metadata, source):
        self.metadata = metadata
        self.sources = {source}


class DistInfo(object):
    def __init__(self, name, version, reqs, extras=(), meta=False):
        self.name = name
        self.version = version
        self.reqs = list(reqs)
        self.extras = extras
        self.meta = meta
        self.hash = hash(self.name + str(self.version))

    def __hash__(self):
        return self.hash

    @lru_cache(maxsize=500)
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
