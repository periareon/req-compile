"""Logic for compiling requirements"""
import logging

import pkg_resources

import qer.dists
import qer.metadata
import qer.repos.pypi
import qer.utils
from qer.utils import parse_requirement, merge_requirements
import qer.repos.repository

from qer.dists import DistributionCollection, RequirementsFile
from qer.repos.repository import NoCandidateException


ROOT_REQ = 'root__a.out'
CONSTRAINTS_REQ = 'constraints__a.out'

BLACKLIST = [
    'setuptools'
]

MAX_DOWNGRADE = 3

LOG = logging.getLogger('qer.compile')


def compile_roots(node, source, repo, dists, depth=1):
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
    logger = logging.LoggerAdapter(LOG, dict(depth=depth))
    logger.debug('Processing node %s', node)

    if node.metadata is not None:

        if node.metadata.meta:
            for req in list(node.dependencies):
                compile_roots(req, node, repo, dists, depth=depth + 1)
        else:
            logger.info('Reusing dist %s %s', node.metadata.name, node.metadata.version)
    else:
        spec_req = node.build_constraints()
        first_failure = None
        original_metadata = None

        for attempt in range(MAX_DOWNGRADE):
            try:
                dist, cached = repo.get_candidate(spec_req)
                source_repo = repo.source_of(spec_req)

                logger.debug('Acquired candidate %s [%s] (%s)', dist, source_repo, 'cached' if cached else 'download')

                nodes_to_recurse = set()
                metadata = None
            except NoCandidateException as no_candidate_ex:
                if attempt == 0:
                    raise no_candidate_ex
                else:
                    break

            try:
                if isinstance(dist, qer.metadata.DistInfo):
                    metadata = dist
                else:
                    metadata = qer.metadata.extract_metadata(dist, origin=source_repo)

                # Save off the original metadata for better error information
                if original_metadata is None:
                    original_metadata = metadata

                nodes_to_recurse = dists.add_dist(metadata, source, source.dependencies[node])
                if nodes_to_recurse:
                    for recurse_node in nodes_to_recurse:
                        for req in list(recurse_node.dependencies):
                            compile_roots(req, recurse_node, repo, dists, depth=depth + 1)
                first_failure = None
                break
            except qer.metadata.MetadataError as meta_error:
                logger.warning('The metadata could not be processed for %s (%s)', node.key, meta_error)
                ex = meta_error
                spec_req = merge_requirements(spec_req,
                                              parse_requirement('{}!={}'.format(meta_error.name, meta_error.version)))
            except NoCandidateException as no_candidate_ex:
                logger.debug('Could not use candidate because some of its dependencies could not be satisfied (%s)',
                             no_candidate_ex)
                ex = no_candidate_ex
                spec_req = merge_requirements(spec_req,
                                              parse_requirement('{}!={}'.format(metadata.name, metadata.version)))

            if first_failure is None:
                first_failure = ex

            for node in nodes_to_recurse:
                dists.remove_dists(node, remove_upstream=False)

        if first_failure is not None:
            nodes_to_recurse = dists.add_dist(original_metadata, source, source.dependencies[node])
            if nodes_to_recurse:
                for recurse_node in nodes_to_recurse:
                    for req in list(recurse_node.dependencies):
                        compile_roots(req, recurse_node, repo, dists, depth=depth + 1)
            raise first_failure


def perform_compile(input_reqs, repo, constraint_reqs=None):
    """
    Perform a compilation using the given inputs and constraints

    Args:
        input_reqs (list[pkg_resources.Requirement] or
                    dict[str, list[pkg_resources.Requirement]]):
            List of mapping of input requirements. If provided a mapping,
            requirements will be kept separate during compilation for better
            insight into the resolved requirements
        repo (qer.repos.Repository): Repository to use as a source of
            Python packages.
        constraint_reqs (list[pkg_resources.Requirement] or None): Constraints to use
            when compiling
    Returns:
        tuple[DistributionCollection, set[DependencyNode], set[DependencyNode]], the solution and the constraints node used for
            the solution
    """
    results = qer.dists.DistributionCollection()

    constraint_node = set()
    nodes = set()
    if constraint_reqs is not None:
        constraint_node = results.add_dist(RequirementsFile(CONSTRAINTS_REQ, constraint_reqs), None, None)
        nodes |= constraint_node

    if isinstance(input_reqs, dict):
        for idx, req_source in enumerate(input_reqs):
            roots = input_reqs[req_source]
            nodes |= results.add_dist(RequirementsFile(req_source, roots), None, None)
    else:
        nodes |= results.add_dist(RequirementsFile(ROOT_REQ, input_reqs), None, None)

    try:
        for node in nodes:
            compile_roots(node, None, repo, dists=results)
    except NoCandidateException as ex:
        ex.results = results
        raise

    return results, nodes - constraint_node, constraint_node
