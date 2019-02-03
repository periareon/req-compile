import collections
import logging

import pkg_resources

import qer.metadata
import qer.pypi


def _filter_roots(roots, extras):
    all_reqs = {}
    for root in roots:
        keep_req = True
        if root.marker:
            if extras:
                keep_req = any(root.marker.evaluate({'extra': extra}) for extra in extras)
            else:
                keep_req = root.marker.evaluate({'extra': None})
        if keep_req:
            all_reqs[root.name] = root
    return all_reqs


class MetadataSources(object):
    def __init__(self, metadata, source):
        self.metadata = metadata
        self.sources = {source}


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
            self.dists[metadata.name].sources.add(source)
        else:
            self.dists[metadata.name] = MetadataSources(metadata, source)

    def remove_dist(self, name):
        del self.dists[name]

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
        return item in self.dists

    def add_global_constraint(self, constraint):
        self.constraints_dist.reqs.append(constraint)

    def build_constraints(self, project_name):
        req = None if project_name == DistributionCollection.CONSTRAINTS_ENTRY else pkg_resources.Requirement.parse(project_name)
        for dist_name, dist in self.dists.iteritems():
            for subreq in dist.metadata.reqs:
                if subreq.name == project_name:
                    req = _merge_requirements(req, subreq)
                    break
        return req


def compile_roots(roots, source, extras=(), dists=None, round=1):
    if not isinstance(roots, list):
        roots = list(roots)

    logger = logging.getLogger('qer.compile')
    if not dists.orig_roots:
        dists.orig_roots = roots

    all_reqs = _filter_roots(roots, extras)

    try:
        for name, item in all_reqs.iteritems():
            specifier = dists.build_constraints(name).specifier
            if name in dists:
                logger.info('Reusing dist %s %s', name, dists.dists[name].metadata.version)
                dists.dists[name].sources.add(source)
                metadata = dists.dists[name].metadata
            else:
                dist = qer.pypi.download_candidate(name, specifier=specifier)
                metadata = qer.metadata.extract_metadata(dist)
                dists.add_dist(metadata, source)

                # See how the new constraints do with the already collected reqs
                for dist in dists.dists.values():
                    if dist.metadata.name != DistributionCollection.CONSTRAINTS_ENTRY:
                        constraints = dists.build_constraints(dist.metadata.name)
                        if not constraints.specifier.contains(dist.metadata.version):
                            logger.error('Already select dist violated (%s %s)', dist.metadata.name,dist.metadata.version)

                            # Remove all downstream reqs
                            dists.remove_source(dist.metadata.name)
                            dists.remove_dist(dist.metadata.name)

                            dists.add_global_constraint(pkg_resources.Requirement.parse(
                                '{}!={}'.format(dist.metadata.name, dist.metadata.version)))
                            return compile_roots(dists.orig_roots, 'rerun',
                                                 extras=extras, dists=dists, round=round+1)


            compile_roots(metadata.reqs, name, dists=dists, round=round)
    except qer.pypi.NoCandidateException as ex:
        raise

    return dists


def _merge_requirements(req1, req2):
    if req1 is not None and req2 is None:
        return req1
    if req2 is not None and req1 is None:
        return req2

    assert req1.name == req2.name
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

    req_str = req1.name + ','.join(''.join(parts) for parts in all_specs) + new_marker
    return pkg_resources.Requirement.parse(req_str)


if __name__ == '__main__':
    logging.basicConfig()
    logging.getLogger().setLevel(logging.INFO)

    results = DistributionCollection([pkg_resources.Requirement.parse('pylint<1.9')])
    dists = compile_roots(roots=[
        pkg_resources.Requirement.parse('pymodbus'),
        pkg_resources.Requirement.parse('pylint'),
        pkg_resources.Requirement.parse('pytest'),
        pkg_resources.Requirement.parse('pytest-mccabe'),
        pkg_resources.Requirement.parse('pytest-timeout'),
    ], source='#constraints#', dists=results)

    for dist in dists.dists.values():
        constraints = dists.build_constraints(dist.metadata.name)
        if constraints is not None:
            constraints = '- ' + str(constraints.specifier)
        else:
            constraints = ''
        print '{}=={} # via {} {}'.format(dist.metadata.name, dist.metadata.version, ','.join(dist.sources), constraints)
