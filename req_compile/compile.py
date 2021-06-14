# pylint: disable=too-many-nested-blocks
"""Logic for compiling requirements"""
from __future__ import print_function

import logging
import operator
import sys
from collections import defaultdict
from typing import Dict, Iterable, Mapping, Optional, Set, Tuple

import pkg_resources
import six

import req_compile.containers
import req_compile.dists
import req_compile.errors
import req_compile.metadata
import req_compile.repos.pypi
import req_compile.repos.repository
import req_compile.utils
from req_compile.containers import RequirementContainer
from req_compile.dists import DependencyNode, DistributionCollection
from req_compile.errors import NoCandidateException
from req_compile.repos.repository import BaseRepository
from req_compile.repos.source import SourceRepository
from req_compile.utils import (
    is_pinned_requirement,
    merge_requirements,
    normalize_project_name,
    parse_requirement,
    parse_version,
)
from req_compile.versions import is_possible

MAX_COMPILE_DEPTH = 80
MAX_DOWNGRADE = 3

LOG = logging.getLogger("req_compile.compile")


class CompileOptions(object):
    """Static options for a compile_roots"""

    extras = None  # type: Optional[Iterable[str]]
    allow_circular_dependencies = True
    pinned_requirements = {}  # type: Mapping[str, pkg_resources.Requirement]


def compile_roots(
    node,  # type: DependencyNode
    source,  # type: Optional[DependencyNode]
    repo,  # type: BaseRepository
    dists,  # type: DistributionCollection
    options,  # type: CompileOptions
    depth=1,  # type: int
    max_downgrade=MAX_DOWNGRADE,  # type: int
    _path=None,
):  # pylint: disable=too-many-statements,too-many-locals,too-many-branches
    # type: (...) -> None
    """
    Args:
        node: The node to compile
        source: The source node of this provided node. This is used to build the graph
        repo: The repository to provide candidates.
        dists: The solution that is being built incrementally
        options: Static options for the compile (including extras)
        depth: Depth the compilation has descended into
        max_downgrade: The maximum number of version downgrades that will be allowed for conflicts
        _path: The path back to root - all nodes along the way
    """
    if _path is None:
        _path = set()

    logger = LOG
    logger.debug("Processing node %s", node)
    if node.key in dists and dists[node.key] is not node:
        logger.debug("No need to process this node, it has been removed")
    elif node.metadata is not None:
        if not node.complete:
            if depth > MAX_COMPILE_DEPTH:
                raise ValueError("Recursion too deep")
            try:
                for req in sorted(node.dependencies, key=lambda node: node.key):
                    if req in _path:
                        if options.allow_circular_dependencies:
                            logger.error(
                                "Skipping node %s because it includes this node",
                                req,
                            )
                        else:
                            raise ValueError(
                                "Circular dependency: {node} -> {req} -> {node}".format(
                                    node=node,
                                    req=req,
                                )
                            )
                    else:
                        compile_roots(
                            req,
                            node,
                            repo,
                            dists,
                            options,
                            depth=depth + 1,
                            max_downgrade=max_downgrade,
                            _path=_path | {node},
                        )
                node.complete = True

            except NoCandidateException:
                if max_downgrade == 0:
                    raise
                compile_roots(
                    node,
                    source,
                    repo,
                    dists,
                    options,
                    depth=depth,
                    max_downgrade=0,
                    _path=_path,
                )
        else:
            logger.info("Reusing dist %s %s", node.metadata.name, node.metadata.version)
    else:
        spec_req = node.build_constraints()

        if options.pinned_requirements:
            pin = options.pinned_requirements.get(
                normalize_project_name(spec_req.project_name), spec_req
            )
            spec_req = merge_requirements(spec_req, pin)

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
                if node in source.dependencies:
                    reason = source.dependencies[node]
                    if options.extras and isinstance(metadata.origin, SourceRepository):
                        reason = merge_requirements(
                            reason,
                            parse_requirement(
                                reason.project_name
                                + "["
                                + ",".join(options.extras)
                                + "]"
                            ),
                        )

            nodes_to_recurse = dists.add_dist(metadata, source, reason)
            for recurse_node in sorted(nodes_to_recurse):
                compile_roots(
                    recurse_node,
                    source,
                    repo,
                    dists,
                    options,
                    depth=depth + 1,
                    max_downgrade=max_downgrade,
                    _path=_path,
                )
        except NoCandidateException:
            if max_downgrade == 0:
                raise

            exc_info = sys.exc_info()

            nodes = sorted(node.reverse_deps)

            violate_score = defaultdict(int)  # type: Dict[DependencyNode, int]
            for idx, revnode in enumerate(nodes):
                for next_node in nodes[idx + 1 :]:
                    if not is_possible(
                        merge_requirements(
                            revnode.dependencies[node], next_node.dependencies[node]
                        )
                    ):
                        logger.error(
                            "Requirement %s was not possible. Violating pair: %s %s",
                            node.build_constraints(),
                            revnode,
                            next_node,
                        )
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
            assert bad_meta is not None
            logger.debug("The node %s had the most conflicts", baddest_node)

            new_constraints = [
                parse_requirement("{}!={}".format(bad_meta.name, bad_meta.version))
            ]
            bad_constraint = req_compile.containers.DistInfo(
                "#bad#-{}-{}".format(baddest_node, depth),
                parse_version("0.0.0"),
                new_constraints,
                meta=True,
            )
            dists.remove_dists(baddest_node, remove_upstream=False)
            baddest_node.complete = False
            dists.remove_dists(node, remove_upstream=False)
            node.complete = False

            bad_constraints = dists.add_dist(bad_constraint, None, None)
            try:
                logger.debug("Finding new solutions for %s and %s", node, baddest_node)
                for node_to_compile in (node, baddest_node):
                    compile_roots(
                        node_to_compile,
                        None,
                        repo,
                        dists,
                        options,
                        depth=depth,
                        max_downgrade=max_downgrade - 1,
                        _path=_path,
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
    input_reqs,  # type: Iterable[RequirementContainer]
    repo,  # type: BaseRepository
    constraint_reqs=None,  # type: Iterable[RequirementContainer]
    extras=None,  # type: Iterable[str]
    allow_circular_dependencies=True,  # type: bool
):
    # type: (...) -> Tuple[DistributionCollection, Set[DependencyNode]]
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
        allow_circular_dependencies: Whether or not to allow circular dependencies
    Returns:
        the solution and root nodes used to generate it
    """
    results = req_compile.dists.DistributionCollection()

    constraint_nodes = set()
    nodes = set()
    all_pinned = True
    pinned_requirements = {}

    if constraint_reqs is not None:
        for constraint_source in constraint_reqs:
            all_pinned &= all([is_pinned_requirement(req) for req in constraint_source])
            if all_pinned:
                for req in constraint_source:
                    pinned_requirements[normalize_project_name(req.project_name)] = req

        if not all_pinned:
            for constraint_source in constraint_reqs:
                constraint_node = results.add_dist(constraint_source, None, None)
                constraint_nodes |= constraint_node
                nodes |= constraint_nodes

    roots = set()
    for req_source in input_reqs:
        roots |= results.add_dist(req_source, None, None)

    nodes |= roots

    options = CompileOptions()
    options.allow_circular_dependencies = allow_circular_dependencies
    options.extras = extras

    if all_pinned and constraint_reqs:
        LOG.info("All constraints were pins - no need to solve the constraints")
        options.pinned_requirements = pinned_requirements

    try:
        for node in sorted(nodes):
            compile_roots(node, None, repo, results, options)
    except (NoCandidateException, req_compile.errors.MetadataError) as ex:
        _add_constraints(all_pinned, constraint_reqs, results)
        ex.results = results
        raise

    # Add the constraints in so it will show up as a contributor in the results.
    # The same is done in the exception block above
    _add_constraints(all_pinned, constraint_reqs, results)

    return results, roots


def _add_constraints(all_pinned, constraint_reqs, results):
    # type: (bool, Optional[Iterable[RequirementContainer]], DistributionCollection) -> None
    if all_pinned and constraint_reqs is not None:
        for constraint_source in constraint_reqs:
            results.add_dist(constraint_source, None, None)
