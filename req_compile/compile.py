# pylint: disable=too-many-nested-blocks
"""Logic for compiling requirements"""
from __future__ import print_function
import logging
import operator
import sys
from collections import defaultdict
from typing import Iterable, Tuple, Set, Optional

import six

import req_compile.dists
from req_compile.dists import (
    RequirementContainer,
    DistributionCollection,
    DependencyNode,
)
import req_compile.metadata
import req_compile.metadata.errors
import req_compile.repos.pypi
import req_compile.utils
from req_compile.repos.source import SourceRepository
from req_compile.utils import parse_requirement, merge_requirements
import req_compile.repos.repository

from req_compile.repos.repository import NoCandidateException, BaseRepository
from req_compile.versions import is_possible

MAX_COMPILE_DEPTH = 80
MAX_DOWNGRADE = 3

LOG = logging.getLogger("req_compile.compile")


class CompileOptions(object):
    """Static options for a compile_roots"""

    extras = ()  # type: Iterable[str]
    allow_circular_dependencies = False


def compile_roots(
    node, source, repo, dists, options, depth=1, max_downgrade=MAX_DOWNGRADE
):  # pylint: disable=too-many-statements,too-many-locals,too-many-branches
    # type: (DependencyNode, Optional[DependencyNode], BaseRepository, DistributionCollection, CompileOptions, int, int) -> None
    """
    Args:
        node: The node to compile
        source: The source node of this provided node. This is used to build the graph
        repo: The repository to provide candidates.
        dists: The solution that is being built incrementally
        options: Static options for the compile (including extras)
        depth: Depth the compilation has descended into
        max_downgrade: The maximum number of version downgrades that will be allowed for conflicts
    """
    logger = logging.LoggerAdapter(LOG, dict(depth=depth))
    logger.debug("Processing node %s", node)

    if node.metadata is not None:
        can_reuse = node.complete and all(dep.complete for dep in node.dependencies)
        if not can_reuse:
            if depth > MAX_COMPILE_DEPTH:
                raise ValueError("Recursion too deep")
            try:
                for req in sorted(node.dependencies):
                    if not req.complete or req.metadata is None:
                        is_circular = False

                        for rdep in dists.visit_nodes([req], reverse=True):
                            if rdep is req:
                                is_circular = True
                                if options.allow_circular_dependencies:
                                    logger.debug(
                                        "Skipping node %s because it includes this node",
                                        rdep,
                                    )
                                    break
                                raise ValueError(
                                    "Circular dependency: {node} -> {req} -> {node}".format(
                                        node=node, req=req,
                                    )
                                )
                        if not is_circular:
                            compile_roots(
                                req,
                                node,
                                repo,
                                dists,
                                options,
                                depth=depth + 1,
                                max_downgrade=max_downgrade,
                            )
            except NoCandidateException:
                if max_downgrade == 0:
                    raise
                compile_roots(
                    node, source, repo, dists, options, depth=depth, max_downgrade=0,
                )
        else:
            logger.info("Reusing dist %s %s", node.metadata.name, node.metadata.version)
    else:
        spec_req = node.build_constraints()

        try:
            metadata, cached = repo.get_candidate(spec_req, max_downgrade=max_downgrade)
            logger.debug(
                "Acquired candidate %s %s [%s] (%s)",
                metadata,
                spec_req,
                metadata.origin,
                "cached" if cached else "download",
            )
            reason = None
            if source is not None:
                reason = source.dependencies[node]
                if options.extras and isinstance(metadata.origin, SourceRepository):
                    reason = merge_requirements(
                        reason,
                        parse_requirement(
                            reason.name + "[" + ",".join(options.extras) + "]"
                        ),
                    )

            nodes_to_recurse = dists.add_dist(metadata, source, reason)
            for recurse_node in sorted(nodes_to_recurse):
                for child_node in sorted(recurse_node.dependencies):
                    if child_node in dists.nodes.values():
                        compile_roots(
                            child_node,
                            recurse_node,
                            repo,
                            dists,
                            options,
                            depth=depth + 1,
                            max_downgrade=max_downgrade,
                        )

            node.complete = True
        except NoCandidateException:
            if max_downgrade == 0:
                raise

            exc_info = sys.exc_info()

            nodes = sorted(node.reverse_deps)

            violate_score = defaultdict(int)
            for idx, revnode in enumerate(nodes):
                for next_node in nodes[idx + 1 :]:
                    if not is_possible(
                        merge_requirements(
                            revnode.dependencies[node], next_node.dependencies[node]
                        )
                    ):
                        logger.error("Violating pair: {} {}".format(revnode, next_node))
                        violate_score[revnode] += 1
                        violate_score[next_node] += 1

            try:
                baddest_node = next(
                    node
                    for node, _ in sorted(
                        violate_score.items(), key=operator.itemgetter(1)
                    )
                    if node.metadata is not None and not node.metadata.meta
                )
            except StopIteration:
                six.reraise(*exc_info)

            bad_meta = baddest_node.metadata
            new_constraints = [
                parse_requirement("{}!={}".format(bad_meta.name, bad_meta.version))
            ]
            bad_constraint = req_compile.dists.DistInfo(
                "#bad#-{}-{}".format(baddest_node, depth),
                None,
                new_constraints,
                meta=True,
            )
            dists.remove_dists(baddest_node, remove_upstream=False)
            dists.remove_dists(node, remove_upstream=False)

            bad_constraints = dists.add_dist(bad_constraint, None, None)
            try:
                for node_to_compile in (node, baddest_node):
                    compile_roots(
                        node_to_compile,
                        None,
                        repo,
                        dists,
                        options,
                        depth=depth,
                        max_downgrade=max_downgrade - 1,
                    )

                print(
                    "Could not use {} {} - pin to this version to see why not".format(
                        bad_meta.name, bad_meta.version
                    ),
                    file=sys.stderr,
                )
            finally:
                dists.remove_dists(bad_constraints, remove_upstream=True)


def perform_compile(
    input_reqs,
    repo,
    constraint_reqs=None,
    extras=None,
    allow_circular_dependencies=True,
):
    # type: (Iterable[RequirementContainer], BaseRepository, Iterable[RequirementContainer], Iterable[str], bool) -> Tuple[DistributionCollection, Set[DependencyNode]]
    """
    Perform a compilation using the given inputs and constraints

    Args:
        input_reqs:
            List of mapping of input requirements. If provided a mapping,
            requirements will be kept separate during compilation for better
            insight into the resolved requirements
        repo: Repository to use as a source of Python packages.
        extras: Extras to apply automatically to source projects
        constraint_reqs: Constraints to use when compiling
    Returns:
        tuple[DistributionCollection, set[DependencyNode], set[DependencyNode]],
        the solution and the constraints node used for
            the solution
    """
    results = req_compile.dists.DistributionCollection()

    constraint_nodes = set()
    nodes = set()
    if constraint_reqs is not None:
        for constraint_source in constraint_reqs:
            constraint_node = results.add_dist(constraint_source, None, None)
            constraint_nodes |= constraint_node
            nodes |= constraint_node

    roots = set()
    for req_source in input_reqs:
        roots |= results.add_dist(req_source, None, None)

    nodes |= roots

    options = CompileOptions()
    options.allow_circular_dependencies = allow_circular_dependencies
    options.extras = extras

    try:
        for node in sorted(nodes):
            compile_roots(node, None, repo, results, options)
    except (NoCandidateException, req_compile.metadata.errors.MetadataError) as ex:
        ex.results = results
        raise

    return results, roots
