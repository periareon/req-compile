"""Logic for compiling requirements"""
from __future__ import print_function

import logging

import pkg_resources

import qer.dists
import qer.metadata
import qer.repos.pypi
import qer.utils
from qer.utils import parse_requirement, merge_requirements
import qer.repos.repository

from qer.dists import DistributionCollection
from qer.repos.repository import NoCandidateException


ROOT_REQ = 'root__a.out'
CONSTRAINTS_REQ = 'constraints__a.out'

BLACKLIST = [
    'setuptools'
]

MAX_DOWNGRADE = 3


def compile_roots(node, source, repo, dists, depth=1, verbose=False):
    """

    Args:
        node (qer.dists.DependencyNode):
        source (DependencyNode):
        repo (Repository):
        dists (DistributionCollection):
        depth:
        verbose:

    Returns:

    """
    logger = logging.getLogger('qer.compile')

    if verbose:
        print(' ' * depth + node.key, end='')

    if node.metadata is not None:
        if verbose:
            print(' ... REUSE')
        logger.info('Reusing dist %s %s', node.metadata.name, node.metadata.version)

        if node.metadata.meta:
            for req in list(node.dependencies):
                compile_roots(req, node, repo, dists, depth=depth + 1, verbose=verbose)
    else:
        spec_req = node.build_constraints()
        first_failure = None
        for attempt in range(MAX_DOWNGRADE):
            dist, cached = repo.get_candidate(spec_req)
            source_repo = repo.source_of(spec_req)

            if verbose:
                if cached:
                    print(' ... CACHED[{}] ({})'.format(dist, source_repo))
                else:
                    print(' ... DOWNLOAD ({})'.format(source_repo))

            nodes_to_recurse = set()
            metadata = None

            try:
                if isinstance(dist, qer.metadata.DistInfo):
                    metadata = dist
                else:
                    metadata = qer.metadata.extract_metadata(dist, origin=source_repo)
                nodes_to_recurse = dists.add_dist(metadata, source, source.dependencies[node])
                if nodes_to_recurse:
                    for recurse_node in nodes_to_recurse:
                        for req in list(recurse_node.dependencies):
                            compile_roots(req, recurse_node, repo, dists, depth=depth + 1, verbose=verbose)
                first_failure = None
                break
            except qer.metadata.MetadataError as meta_error:
                ex = meta_error
                spec_req = merge_requirements(spec_req,
                                              parse_requirement('{}!={}'.format(meta_error.name, meta_error.version)))
            except NoCandidateException as no_candidate_ex:
                ex = no_candidate_ex
                spec_req = merge_requirements(spec_req,
                                              parse_requirement('{}!={}'.format(metadata.name, metadata.version)))

            if first_failure is None:
                first_failure = ex

            for node in nodes_to_recurse:
                dists.remove_dists(node, remove_upstream=False)

        if first_failure is not None:
            raise first_failure


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


def perform_compile(input_reqs, repo, constraint_reqs=None):
    """
    Perform a compilation using the given inputs and constraints
    Args:
        input_reqs (list[pkg_resources.Requirement] or
                    dict[str, list[pkg_resources.Requirement]]):
            List of mapping of input requirements. If provided a mapping,
            requirements will be kept separate during compilation for better
            insight into the resolved requirements
        constraint_reqs (list[pkg_resources.Requirement] or None): Constraints to use
            when compiling
    Returns:
        tuple[DistributionCollection, DistributionCollection, dict]
    """
    results = qer.dists.DistributionCollection()

    if constraint_reqs:
        constraint_node = results.add_dist(qer.dists.RequirementsFile(CONSTRAINTS_REQ, constraint_reqs), None, None)

    nodes = set()
    if isinstance(input_reqs, dict):
        fake_reqs = []
        for idx, req_source in enumerate(input_reqs):
            roots = input_reqs[req_source]
            name = '{}{}'.format(ROOT_REQ, idx)
            fake_reqs.append(pkg_resources.Requirement(name))
            nodes |= results.add_dist(qer.dists.RequirementsFile(req_source, roots), None, None)
    else:
        nodes |= results.add_dist(qer.dists.RequirementsFile(ROOT_REQ, input_reqs), None, None)

    try:
        for node in nodes:
            compile_roots(node, None, repo, dists=results)
    except NoCandidateException as ex:
        ex.results = results
        raise

    if constraint_reqs:
        results.remove_dists(list(constraint_node)[0])

    for node in results:
        if node.metadata is None:
            raise NoCandidateException(node.build_constraints(), results=results)
    return results
