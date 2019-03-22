"""Logic for compiling requirements"""
from __future__ import print_function

import logging

import pkg_resources

import qer.dists
import qer.metadata
import qer.repos.pypi
import qer.utils
import qer.repos.repository

from qer.dists import DistributionCollection
from qer.utils import normalize_project_name


ROOT_REQ = 'root__a'
BLACKLIST = [
    DistributionCollection.CONSTRAINTS_ENTRY,
    'setuptools'
]


def compile_roots(root, source, repo, dists=None, depth=1,
                  toplevel=None, wheeldir=None, verbose=True):
    logger = logging.getLogger('qer.compile')

    if verbose:
        print(' ' * depth + str(root), end='')

    recurse_reqs = False
    extras = root.extras
    if root.name in dists:
        normalized_name = normalize_project_name(root.name)

        logger.info('Reusing dist %s %s', root.name, dists.dists[normalized_name].metadata.version)
        reused_dist = dists.dists[normalized_name]
        old_extras = reused_dist.metadata.extras
        reused_dist.add(source, root)
        if old_extras != root.extras or reused_dist.metadata.meta:
            metadata = reused_dist.metadata
            recurse_reqs = True
        if verbose:
            print(' ... REUSE ({})'.format(', '.join(reused_dist.sources.keys())))
    else:
        spec_req = dists.build_constraints(root.name, extras=root.extras)
        dist, cached = repo.get_candidate(spec_req)
        source_repo = repo.source_of(spec_req)

        if verbose:
            if cached:
                print(' ... CACHED ({})'.format(source_repo))
            else:
                print(' ... DOWNLOAD ({})'.format(source_repo))

        extras = qer.utils.merge_extras(root.extras, source_repo.force_extras())

        metadata = qer.metadata.extract_metadata(dist, origin=source_repo, extras=extras)
        dists.add_dist(metadata, source)
        recurse_reqs = True

        # See how the new constraints do with the already collected reqs
        has_violations = False
        for req in metadata.requires(extras):
            normalized_name = normalize_project_name(req.name)
            if normalized_name in dists.dists:
                current_dist = dists.dists[normalized_name]
                constraints = dists.build_constraints(req.name, extras=root.extras)
                has_equality = any(
                    spec.operator == '==' or spec.operator == '===' for spec in constraints.specifier)
                if not constraints.specifier.contains(current_dist.metadata.version, prereleases=has_equality):
                    logger.info('Already selected dist violated (%s %s)',
                                current_dist.metadata.name, current_dist.metadata.version)
                    if verbose:
                        print('------ VIOLATED {} {} -----'.format(current_dist.metadata.name,
                                                                   current_dist.metadata.version))
                    # Remove all downstream reqs
                    dists.remove_dist(current_dist.metadata.name)

                    dists.add_global_constraint(qer.utils.parse_requirement(
                        '{}!={}'.format(current_dist.metadata.name, current_dist.metadata.version)))
                    has_violations = True

        if has_violations:
            # Remove the dist responsible for this violation
            dists.remove_dist(metadata.name)

            compile_roots(toplevel, 'rerun', repo,
                          dists=dists, depth=1,
                          toplevel=toplevel,
                          wheeldir=wheeldir)
            return

    if recurse_reqs:
        for req in metadata.requires(extras):
            compile_roots(req, normalize_project_name(root.name), repo, dists=dists, depth=depth + 1,
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


def perform_compile(input_reqs, wheeldir, repo, constraint_reqs=None, solution=None):
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
        solution (DistributionCollection): Optionally, provide a possible solution
            to consider when compiling. Existing distributions will be modified as
            necessary to solve the solution
    Returns:
        tuple[DistributionCollection, DistributionCollection, dict]
    """
    root_req = qer.utils.parse_requirement(ROOT_REQ)
    if constraint_reqs:
        if all(qer.utils.is_pinned_requirement(req) for req in constraint_reqs):
            constraint_results = qer.dists.DistributionCollection(constraint_reqs)
            constraints = constraint_reqs
        else:
            constraint_results = qer.dists.DistributionCollection()
            constraint_results.add_dist(_build_root_metadata(constraint_reqs, ROOT_REQ), ROOT_REQ)

            compile_roots(root_req, ROOT_REQ, repo, dists=constraint_results,
                          toplevel=root_req,
                          wheeldir=wheeldir)

            constraints = list(_generate_constraints(constraint_results))
    else:
        constraint_results = qer.dists.DistributionCollection()
        constraints = None

    results = qer.dists.DistributionCollection(constraints)

    if solution is not None:
        for dist in solution:
            results.dists[qer.utils.normalize_project_name(dist.metadata.name)] = dist

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

        if solution is not None:
            removed_one = True
            while removed_one:
                removed_one = False
                for dist in list(results.dists.values()):
                    if not dist.sources:
                        if results.remove_dist(dist.metadata.name):
                            removed_one = True

        return results, constraint_results, root_mapping
    except qer.repos.repository.NoCandidateException as ex:
        ex.results = results
        ex.constraint_results = constraint_results
        ex.mapping = root_mapping
        raise ex
