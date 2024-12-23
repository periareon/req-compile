# pylint: disable=too-many-nested-blocks
"""Logic for compiling requirements"""
from __future__ import print_function

import itertools
import logging
import operator
import os
from collections import defaultdict
from typing import Dict, Iterable, Mapping, Optional, Set, Tuple

import pkg_resources

import req_compile.containers
import req_compile.dists
import req_compile.errors
import req_compile.metadata
import req_compile.repos.pypi
import req_compile.repos.repository
import req_compile.utils
from req_compile.containers import RequirementContainer
from req_compile.dists import DependencyNode, DistributionCollection
from req_compile.errors import MetadataError, NoCandidateException
from req_compile.repos.repository import Repository
from req_compile.repos.source import SourceRepository
from req_compile.utils import (
    NormName,
    is_pinned_requirement,
    merge_requirements,
    normalize_project_name,
    parse_requirement,
    parse_version,
)
from req_compile.versions import is_possible

MAX_COMPILE_DEPTH = int(os.environ.get("REQ_COMPILE_MAX_DEPTH", "80"))
MAX_DOWNGRADE = int(os.environ.get("REQ_COMPILE_MAX_DOWNGRADE", "20"))

LOG = logging.getLogger("req_compile.compile")


class AllOnlyBinarySet(set):
    """A set which contains any item."""

    def __bool__(self) -> bool:
        return True

    def __contains__(self, item: object) -> bool:
        return True


class CompileOptions:
    """Static options for a compile_roots."""

    extras: Optional[Iterable[str]] = None
    allow_circular_dependencies: bool = True
    pinned_requirements: Mapping[NormName, pkg_resources.Requirement] = {}
    only_binary: Set[NormName] = set()


def _get_strictest_reverse_dep(node: DependencyNode) -> Optional[DependencyNode]:
    """Get the strictest constraint from all reverse dependencies.

    Args:
        node: The node to check.

    Returns:
        The single reverse dependency that was the most conflicting. If no reverse
            dependency can be implicated, return None.
    """
    nodes = sorted(node.reverse_deps)

    violate_score: Dict[DependencyNode, int] = defaultdict(int)
    for idx, revnode in enumerate(nodes):
        for next_node in nodes[idx + 1 :]:
            if not is_possible(
                merge_requirements(
                    revnode.dependencies[node], next_node.dependencies[node]
                )
            ):
                violate_score[revnode] += 1
                violate_score[next_node] += 1
    try:
        # Pick the worst, but filter out meta dependencies. We can't select new versions
        # if the entry comes directly from a requirements file or similar source.
        return next(
            scored_node
            for scored_node, _ in sorted(
                violate_score.items(), key=operator.itemgetter(1)
            )
            if scored_node.metadata is not None and not scored_node.metadata.meta
        )
    except StopIteration:
        return None


def compile_roots(
    node: DependencyNode,
    source: Optional[DependencyNode],
    repo: Repository,
    dists: DistributionCollection,
    options: CompileOptions,
    depth: int = 1,
    max_downgrade: int = MAX_DOWNGRADE,
    _path: Optional[Set[DependencyNode]] = None,
) -> None:  # pylint: disable=too-many-statements,too-many-locals,too-many-branches
    """
    Args:
        node: The node to compile
        source: The source node of this provided node. This is used to build the graph
        repo: The repository to provide candidate distributions.
        dists: The solution that is being built incrementally
        options: Static options for the compile (including extras)
        depth: Depth the compilation has descended into
        max_downgrade: The maximum number of version downgrades that will be allowed for conflicts
        _path: The path back to root - all nodes along the way

    Raises:
        NoCandidateException: If no candidate could be found for a requirement.
    """
    if _path is None:
        _path = set()

    logger = LOG
    logger.debug("Processing node %s", node)

    if depth > MAX_COMPILE_DEPTH:
        raise ValueError("Recursion too deep")

    if node.key not in dists or dists[node.key] is not node:
        logger.debug("No need to process this node, it has been removed")
        return

    if node.complete:
        assert node.metadata is not None
        logger.info("Reusing dist %s %s", node.metadata.name, node.metadata.version)
        return

    # This node is unsolved, find a candidate from the provided repository `repo`.
    if node.metadata is None:
        spec_req = node.build_constraints()

        spec_name = normalize_project_name(spec_req.project_name)
        if options.pinned_requirements:
            pin = options.pinned_requirements.get(spec_name, spec_req)
            spec_req = merge_requirements(spec_req, pin)

        if not is_possible(spec_req):
            logger.info("Requirement conflict for %s (%s)", node, spec_req)
            # Try walking back. Some reverse dependency contributed a requirement
            # expression that lead to this node being unsolveable. Instead of attempting
            # to search the full space, find the one that conflicts with the most
            # other reverse dependencies and add a new constraint to keep the same
            # version from being selected.
            reverse_dep = _get_strictest_reverse_dep(node)
            if reverse_dep is None:
                raise NoCandidateException(spec_req)

            assert reverse_dep.metadata is not None
            new_constraints = [
                parse_requirement(
                    "{}!={}".format(
                        reverse_dep.metadata.name, reverse_dep.metadata.version
                    )
                )
            ]
            bad_dist = req_compile.containers.DistInfo(
                "#donotuse#-{}-{}-{}".format(
                    reverse_dep.key,
                    str(reverse_dep.metadata.version).replace("-", "_"),
                    depth,
                ),
                parse_version("0.0.0"),
                new_constraints,
                meta=True,
            )
            # Unsolve.
            dists.remove_dists(reverse_dep, remove_upstream=False)
            bad_constraint = dists.add_dist(bad_dist, None, None)
            try:
                # Resolve with the new constraint and attempt to carry on.
                compile_roots(
                    reverse_dep,
                    None,
                    repo,
                    dists,
                    options,
                    depth=depth + 1,
                    max_downgrade=max_downgrade - 1,
                    _path=_path - {reverse_dep},
                )
            finally:
                dists.remove_dists(bad_constraint, remove_upstream=False)
            return

        metadata, cached = repo.get_dist(
            spec_req,
            allow_source_dist=spec_name not in options.only_binary,
            max_downgrade=max_downgrade,
        )
        logger.debug(
            "Acquired candidate %s %s [%s] (%s)",
            metadata,
            spec_req,
            metadata.origin,
            "cached" if cached else "download",
        )

        # Add extras to the "reason" if the commandline option was specified.
        # This only applies to sourcd repositories.
        reason: Optional[pkg_resources.Requirement] = None
        if source is not None and node in source.dependencies:
            reason = source.dependencies[node]
            if (
                reason is not None
                and options.extras
                and isinstance(metadata.origin, SourceRepository)
            ):
                reason = merge_requirements(
                    reason,
                    parse_requirement(
                        reason.project_name + "[" + ",".join(options.extras) + "]"
                    ),
                )

        new_node = dists.add_dist(metadata, source, reason)
        assert new_node is node

    # Solve each dependency of the node. Some may already be complete.
    for dep in sorted(node.dependencies):
        if dep in _path:
            if options.allow_circular_dependencies:
                logger.info(
                    "Skipping node %s because it includes this node",
                    dep,
                )
            else:
                raise ValueError(
                    "Circular dependency: {node} -> {dep} -> {node}".format(
                        node=node,
                        dep=dep,
                    )
                )
        else:
            compile_roots(
                dep,
                node,
                repo,
                dists,
                options,
                depth=depth + 1,
                max_downgrade=max_downgrade,
                _path=_path | {node},
            )


def perform_compile(
    input_reqs: Iterable[RequirementContainer],
    repo: Repository,
    constraint_reqs: Optional[Iterable[RequirementContainer]] = None,
    remove_constraints: bool = False,
    extras: Optional[Iterable[str]] = None,
    allow_circular_dependencies: bool = True,
    only_binary: Optional[Set[NormName]] = None,
    max_downgrade: Optional[int] = None,
) -> Tuple[DistributionCollection, Set[DependencyNode]]:
    """Perform a compilation using the given inputs and constraints.

    Args:
        input_reqs:
            List of mapping of input requirements. If provided a mapping,
            requirements will be kept separate during compilation for better
            insight into the resolved requirements
        repo: Repository to use as a source of Python packages.
        extras: Extras to apply automatically to source projects
        constraint_reqs: Constraints to use when compiling
        remove_constraints: Whether to remove the constraints from the solution. By default,
            constraints are added, so you can see why a requirement was pinned to a particular
            version.
        allow_circular_dependencies: Whether to allow circular dependencies
        only_binary: Set of projects that should only consider binary distributions.
        max_downgrade: The maximum number of version downgrades that will be allowed for conflicts.

    Returns:
        the solution and root nodes used to generate it
    """
    results = req_compile.dists.DistributionCollection()

    constraint_nodes = set()
    nodes = set()
    all_pinned = True
    pinned_requirements: Dict[NormName, pkg_resources.Requirement] = {}

    if constraint_reqs is not None:
        for constraint_source in constraint_reqs:
            all_pinned &= all([is_pinned_requirement(req) for req in constraint_source])
            if all_pinned:
                for req in constraint_source:
                    pinned_requirements[normalize_project_name(req.project_name)] = req

        if not all_pinned:
            for constraint_source in constraint_reqs:
                constraint_nodes.add(results.add_dist(constraint_source, None, None))
            nodes |= constraint_nodes

    roots = set()
    for req_source in input_reqs:
        roots.add(results.add_dist(req_source, None, None))

    nodes |= roots

    options = CompileOptions()
    options.allow_circular_dependencies = allow_circular_dependencies
    options.extras = extras
    options.only_binary = only_binary or set()

    if all_pinned and constraint_reqs:
        LOG.info("All constraints were pins - no need to solve the constraints")
        options.pinned_requirements = pinned_requirements

    if max_downgrade is None:
        max_downgrade = MAX_DOWNGRADE

    try:
        LOG.info("Compiling %d root(s)", len(nodes))
        idx = itertools.count()
        # Compile until all root nodes have a solution.
        while any(not node.complete for node in nodes):
            if next(idx) > 1000:
                for node in sorted(results):
                    print(f"{node} {node.complete}")
                raise ValueError("Iteration limit hit. This is a bug in req-compile.")
            for node in sorted(nodes):
                compile_roots(
                    node, None, repo, results, options, max_downgrade=max_downgrade
                )
    except (NoCandidateException, MetadataError) as ex:
        if not remove_constraints:
            _add_constraints(all_pinned, constraint_reqs, results)
        ex.results = results
        raise

    if not remove_constraints:
        # Add the constraints in, so it will show up as a contributor in the results.
        # The same is done in the exception block above
        _add_constraints(all_pinned, constraint_reqs, results)

    return results, roots


def _add_constraints(
    all_pinned: bool,
    constraint_reqs: Optional[Iterable[RequirementContainer]],
    results: DistributionCollection,
) -> None:
    if all_pinned and constraint_reqs is not None:
        for constraint_source in constraint_reqs:
            results.add_dist(constraint_source, None, None)
