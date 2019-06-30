"""Logic for compiling requirements"""
import logging
import sys

import six

import qer.dists
import qer.metadata
import qer.repos.pypi
import qer.utils
from qer.utils import parse_requirement, merge_requirements
import qer.repos.repository

from qer.dists import RequirementsFile
from qer.repos.repository import NoCandidateException

MAX_DOWNGRADE = 3

LOG = logging.getLogger('qer.compile')


def compile_roots(node, source, repo, dists, depth=1):  # pylint: disable=too-many-locals,too-many-branches
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
                metadata, cached = repo.get_candidate(spec_req)

                logger.debug('Acquired candidate %s [%s] (%s)',
                             metadata, metadata.origin, 'cached' if cached else 'download')

                nodes_to_recurse = set()
            except NoCandidateException:
                if attempt == 0:
                    raise
                break

            try:
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
                ex = sys.exc_info()
                spec_req = merge_requirements(spec_req,
                                              parse_requirement('{}!={}'.format(meta_error.name, meta_error.version)))
            except NoCandidateException as no_candidate_ex:
                logger.debug('Could not use candidate because some of its dependencies could not be satisfied (%s)',
                             no_candidate_ex)
                ex = sys.exc_info()
                spec_req = merge_requirements(spec_req,
                                              parse_requirement('{}!={}'.format(metadata.name, metadata.version)))

            if first_failure is None:
                first_failure = ex

            for child_node in nodes_to_recurse:
                dists.remove_dists(child_node, remove_upstream=False)

        if first_failure is not None:
            if original_metadata is not None:
                nodes_to_recurse = dists.add_dist(original_metadata, source, source.dependencies[node])
                if nodes_to_recurse:
                    for recurse_node in nodes_to_recurse:
                        for req in list(recurse_node.dependencies):
                            compile_roots(req, recurse_node, repo, dists, depth=depth + 1)
            six.reraise(*first_failure)


def perform_compile(input_reqs, repo, constraint_reqs=None):
    """
    Perform a compilation using the given inputs and constraints

    Args:
        input_reqs (dict[str, list[pkg_resources.Requirement]]):
            List of mapping of input requirements. If provided a mapping,
            requirements will be kept separate during compilation for better
            insight into the resolved requirements
        repo (qer.repos.Repository): Repository to use as a source of
            Python packages.
        constraint_reqs (dict[str, list[pkg_resources.Requirement]] or None): Constraints to use
            when compiling
    Returns:
        tuple[DistributionCollection, set[DependencyNode], set[DependencyNode]],
        the solution and the constraints node used for
            the solution
    """
    results = qer.dists.DistributionCollection()

    constraint_nodes = set()
    nodes = set()
    if constraint_reqs is not None:
        for constraint_source in constraint_reqs:
            constraint_node = results.add_dist(RequirementsFile(constraint_source, constraint_reqs[constraint_source]),
                                               None, None)
            constraint_nodes |= constraint_node
            nodes |= constraint_node

    for req_source in input_reqs:
        nodes |= results.add_dist(RequirementsFile(req_source, input_reqs[req_source]), None, None)

    try:
        for node in nodes:
            compile_roots(node, None, repo, dists=results)
    except NoCandidateException as ex:
        ex.results = results
        raise

    return results, nodes - constraint_nodes
