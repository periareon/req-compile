"""Logic for compiling requirements"""
from __future__ import print_function

import logging
from contextlib import closing

import pkg_resources

import qer.dists
import qer.metadata
import qer.pypi
import qer.utils
import qer.repository

from qer import utils
from qer.dists import DistributionCollection
from qer.utils import normalize_project_name


ROOT_REQ = 'root__a'
BLACKLIST = [
    DistributionCollection.CONSTRAINTS_ENTRY,
    'setuptools'
]


def compile_roots(root, source, repo, dists=None, round=1, toplevel=None, wheeldir=None):
    logger = logging.getLogger('qer.compile')

    # print(' ' * round + str(root), end='')

    recurse_reqs = False
    download = True

    extras = root.extras
    if root.name in dists:
        normalized_name = normalize_project_name(root.name)

        logger.info('Reusing dist %s %s', root.name, dists.dists[normalized_name].metadata.version)
        dists.dists[normalized_name].sources.add(source)
        metadata = dists.dists[normalized_name].metadata
        if metadata.extras != root.extras:
            recurse_reqs = True
            extras = qer.utils.merge_extras(metadata.extras, root.extras)
            metadata.extras = extras
        # print(' ... REUSE')
        if metadata.meta:
            recurse_reqs = True
        download = False

    if download:
        spec_req = dists.build_constraints(root.name, extras=root.extras)
        dist, cached = repo.get_candidate(spec_req)

        source = repo.source_of(spec_req)

        # if cached:
        #     print(' ... CACHED ({})'.format(source))
        # else:
        #     print(' ... DOWNLOAD ({})'.format(source))

        metadata = qer.metadata.extract_metadata(dist, extras=root.extras)
        dists.add_dist(metadata, source)
        recurse_reqs = True

        # See how the new constraints do with the already collected reqs
        has_violations = False
        for req in metadata.requires(extras):
            normalized_name = normalize_project_name(req.name)
            if normalized_name in dists.dists:
                current_dist = dists.dists[normalized_name]
                constraints = dists.build_constraints(req.name, extras=root.extras)
                if not constraints.specifier.contains(current_dist.metadata.version, prereleases=False):
                    logger.info('Already selected dist violated (%s %s)',
                                 current_dist.metadata.name, current_dist.metadata.version)
                    # print('------ VIOLATED {} {} -----'.format(current_dist.metadata.name, current_dist.metadata.version))
                    # Remove all downstream reqs
                    dists.remove_source(current_dist.metadata.name)
                    dists.remove_dist(current_dist.metadata.name)

                    dists.add_global_constraint(utils.parse_requirement(
                        '{}!={}'.format(current_dist.metadata.name, current_dist.metadata.version)))
                    has_violations = True

        if has_violations:
            # Remove the dist responsible for this violation
            dists.remove_source(metadata.name)
            dists.remove_dist(metadata.name)

            return compile_roots(toplevel, 'rerun', repo,
                                 dists=dists, round=1,
                                 toplevel=toplevel,
                                 wheeldir=wheeldir)

    if recurse_reqs:
        for req in metadata.requires(extras):
            compile_roots(req, normalize_project_name(root.name), repo, dists=dists, round=round + 1,
                          toplevel=toplevel, wheeldir=wheeldir)


def _generate_constraints(dists):
    for dist in dists:
        if dist.metadata.name in BLACKLIST:
            continue
        if dist.metadata.name.startswith(ROOT_REQ):
            continue

        req = dists.build_constraints(dist.metadata.name)
        if req.specifier:
            yield req


def _build_root_metadata(roots, name):
    return qer.dists.DistInfo(name, '0', roots, meta=True)


def perform_compile(input_reqs, wheeldir, repo, constraint_reqs=None, index_url=None, find_links=None):
    """
    Perform a compilation using the given inputs and constraints
    Args:
        input_reqs (list[pkg_resources.Requirement] or
                    dict[str, list[pkg_resources.Requirement]]):
            List of mapping of input requirements. If provided a mapping,
            requirements will be kept separate during compilation for better
            insight into the resolved requirements
        wheeldir (str): Location to download wheels to and to use as a cache
        constraint_reqs (list[pkg_resources.Requirement] or None): Constraints to use
            when compiling
        index_url (str): Index URL to download package versions and contents from
        find_links (str): Index URL to download package versions and contents from

    Returns:
        tuple[DistributionCollection, DistributionCollection, dict]
    """
    root_req = utils.parse_requirement(ROOT_REQ)
    constraints = None
    constraint_results = qer.dists.DistributionCollection()
    if constraint_reqs:
        constraint_results = qer.dists.DistributionCollection()
        constraint_results.add_dist(_build_root_metadata(constraint_reqs, ROOT_REQ), ROOT_REQ)

        compile_roots(root_req, ROOT_REQ, repo, dists=constraint_results,
                      toplevel=root_req,
                      wheeldir=wheeldir)

        constraints = list(_generate_constraints(constraint_results))

    results = qer.dists.DistributionCollection(constraints)
    root_mapping = {}
    if isinstance(input_reqs, dict):
        fake_reqs = []
        for idx, req_source in enumerate(input_reqs):
            roots = input_reqs[req_source]
            name = '{}{}'.format(ROOT_REQ, idx)
            root_mapping[name] = req_source
            dist_info = _build_root_metadata(roots, name)
            fake_reqs.append(pkg_resources.Requirement(name))
            results.add_dist(dist_info,
                             req_source)
        results.add_dist(_build_root_metadata(fake_reqs, ROOT_REQ), ROOT_REQ)
    else:
        results.add_dist(_build_root_metadata(input_reqs, ROOT_REQ), ROOT_REQ)

    try:
        compile_roots(root_req, ROOT_REQ, repo, dists=results,
                      toplevel=root_req,
                      wheeldir=wheeldir)

        return results, constraint_results, root_mapping
    except qer.repository.NoCandidateException as ex:
        ex.results = results
        ex.constraint_results = constraint_results
        ex.mapping = root_mapping
        raise ex
