import logging

import pkg_resources

import qer.metadata
import qer.pypi


class MetadataSources(object):
    def __init__(self, metadata, source):
        self.metadata = metadata
        self.sources = {source}


def _normalize_project_name(project_name):
    return project_name.lower().replace('-', '_').replace('.', '_')


class DistributionCollection(object):
    CONSTRAINTS_ENTRY = '#constraints#'

    def __init__(self, constraints=None):
        self.dists = {}
        constraints_dist = qer.metadata.DistInfo()
        constraints_dist.name = '#constraints#'
        constraints_dist.reqs = constraints or []
        constraints_dist.version = None
        self.constraints_dist = constraints_dist
        self.dists[DistributionCollection.CONSTRAINTS_ENTRY] = MetadataSources(
            constraints_dist, DistributionCollection.CONSTRAINTS_ENTRY)
        self.orig_roots = None

    def add_dist(self, metadata, source):
        if metadata.name in self.dists:
            self.dists[_normalize_project_name(metadata.name)].sources.add(source)
        else:
            self.dists[_normalize_project_name(metadata.name)] = MetadataSources(metadata, source)

    def remove_dist(self, name):
        del self.dists[_normalize_project_name(name)]

    def remove_source(self, source):
        dists_to_remove = []
        for dist in self.dists.itervalues():
            if source in dist.sources:
                dist.sources.remove(source)
                if not dist.sources:
                    dists_to_remove.append(dist.metadata.name)

        for dist in dists_to_remove:
            del self.dists[dist]

    def __contains__(self, item):
        return _normalize_project_name(item) in self.dists

    def add_global_constraint(self, constraint):
        self.constraints_dist.reqs.append(constraint)

    def build_constraints(self, project_name):
        normalized_name = _normalize_project_name(project_name)
        req = None if normalized_name == DistributionCollection.CONSTRAINTS_ENTRY else pkg_resources.Requirement.parse(normalized_name)
        for dist_name, dist in self.dists.iteritems():
            for subreq in dist.metadata.reqs:
                if _normalize_project_name(subreq.name) == normalized_name:
                    req = _merge_requirements(req, subreq)
                    break
        return req

    def get_reverse_deps(self, project_name):
        reverse_deps = {}
        normalized_name = _normalize_project_name(project_name)
        for dist_name, dist in self.dists.iteritems():
            for subreq in dist.metadata.reqs:
                if _normalize_project_name(subreq.name) == normalized_name:
                    reverse_deps[dist_name] = subreq
                    break
        return reverse_deps


def compile_roots(root, source, extras=(), dists=None, round=1, index_url=None, toplevel=None, session=None):
    logger = logging.getLogger('qer.compile')

    if not qer.metadata.filter_req(root, extras):
        return

    specifier = dists.build_constraints(root.name).specifier
    if root.name in dists:
        normalized_name = _normalize_project_name(root.name)
        logger.info('Reusing dist %s %s', root.name, dists.dists[normalized_name].metadata.version)
        dists.dists[normalized_name].sources.add(source)
        metadata = dists.dists[normalized_name].metadata
    else:
        try:
            dist = qer.pypi.download_candidate(root.name, specifier=specifier,
                                               index_url=index_url, session=session)
        except qer.pypi.NoCandidateException as ex:
            logger.error('No candidate for %s. Contributions: %s',
                         ex.project_name, dists.get_reverse_deps(ex.project_name))
            raise

        metadata = qer.metadata.extract_metadata(dist, extras=extras)
        dists.add_dist(metadata, source)

        # See how the new constraints do with the already collected reqs
        for dist in dists.dists.values():
            if dist.metadata.name != DistributionCollection.CONSTRAINTS_ENTRY:
                constraints = dists.build_constraints(dist.metadata.name)
                if not constraints.specifier.contains(dist.metadata.version):
                    logger.error('Already selected dist violated (%s %s)', dist.metadata.name, dist.metadata.version)

                    # Remove all downstream reqs
                    dists.remove_source(dist.metadata.name)
                    dists.remove_dist(dist.metadata.name)

                    dists.add_global_constraint(pkg_resources.Requirement.parse(
                        '{}!={}'.format(dist.metadata.name, dist.metadata.version)))
                    return compile_roots(toplevel, 'rerun',
                                         extras=extras, dists=dists, round=round+1,
                                         toplevel=toplevel, index_url=index_url, session=session)

    for req in metadata.reqs:
        compile_roots(req, _normalize_project_name(root.name), dists=dists, round=round,
                      toplevel=toplevel, index_url=index_url, session=session)


def _merge_requirements(req1, req2):
    if req1 is not None and req2 is None:
        return req1
    if req2 is not None and req1 is None:
        return req2

    assert _normalize_project_name(req1.name) == _normalize_project_name(req2.name)
    all_specs = set(req1.specs or []) | set(req2.specs or [])
    if req1.marker and req2.marker and str(req1.marker) != str(req2.marker):
        if str(req1.marker) in str(req2.marker):
            new_marker = ';' + str(req2.marker)
        elif str(req2.marker) in str(req1.marker):
            new_marker = ';' + str(req1.marker)
        else:
            new_marker = ';' + str(req1.marker) + ' and ' + str(req2.marker)
    elif req1.marker:
        new_marker = ';' + str(req1.marker)
    elif req2.marker:
        new_marker = ';' + str(req2.marker)
    else:
        new_marker = ''

    req_str = _normalize_project_name(req1.name) + ','.join(''.join(parts) for parts in all_specs) + new_marker
    return pkg_resources.Requirement.parse(req_str)
