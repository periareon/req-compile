# pylint: disable=too-many-nested-blocks
"""Logic for compiling requirements"""

import itertools
import logging
import operator
import os
from collections import defaultdict
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

import packaging.requirements
import packaging.version

import req_compile.containers
import req_compile.dists
from req_compile.containers import RequirementContainer
from req_compile.dists import DependencyNode, DistributionCollection
from req_compile.errors import (
    MetadataError,
    NoCandidateException,
    NoCommonVersionException,
    PinConflictException,
    Rejection,
)
from req_compile.repos.repository import Repository
from req_compile.repos.source import SourceRepository
from req_compile.target import TargetEnvironment
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
# The number of times solutions compiled together are resolved again after one
# of them rejected a version another had chosen.
MAX_GROUP_PASSES = int(os.environ.get("REQ_COMPILE_MAX_GROUP_PASSES", "20"))

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
    pinned_requirements: Mapping[NormName, packaging.requirements.Requirement] = {}
    # Requirements applied to a project only if it is required, which yield when
    # the project cannot satisfy them: `PinConflictException` is raised instead of
    # resolving the reverse dependencies differently. Solutions compiled together
    # use these to keep their versions aligned, see `perform_compile_group`.
    soft_pins: Mapping[NormName, packaging.requirements.Requirement] = {}
    only_binary: Set[NormName] = set()


def _get_strictest_reverse_dep(
    node: DependencyNode,
    soft_pin: Optional[packaging.requirements.Requirement] = None,
) -> Optional[DependencyNode]:
    """Get the strictest constraint from all reverse dependencies.

    Args:
        node: The node to check.
        soft_pin: A soft pin on the node, scored like a reverse dependency that
            cannot itself be walked back.

    Returns:
        The single reverse dependency that was the most conflicting. If no reverse
            dependency can be implicated, return None.
    """
    nodes = sorted(node.reverse_deps)

    violate_score: Dict[DependencyNode, int] = defaultdict(int)
    for idx, revnode in enumerate(nodes):
        if soft_pin is not None and not is_possible(
            merge_requirements(revnode.dependencies[node], soft_pin)
        ):
            violate_score[revnode] += 1
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
            # Do not walk back source repositories, this would never be expected and would
            # cause another index to be searched, possibly selecting an older version of the
            # source repository that was published to an index in the past.
            and not isinstance(scored_node.metadata.origin, SourceRepository)
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
    max_downgrade: Optional[int] = MAX_DOWNGRADE,
    _path: Optional[Tuple[DependencyNode, ...]] = None,
    _walkback_budget: Optional[int] = None,
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
            (None means unlimited).
        _path: The path back to root - all nodes along the way
        _walkback_budget: Remaining walkback attempts before giving up (internal).

    Raises:
        NoCandidateException: If no candidate could be found for a requirement.
    """
    if _path is None:
        _path = ()
    if _walkback_budget is None:
        if max_downgrade is None:
            _walkback_budget = MAX_COMPILE_DEPTH
        else:
            _walkback_budget = max_downgrade

    logger = LOG

    if depth > MAX_COMPILE_DEPTH:
        path_str = " -> ".join(str(n.key) for n in _path)
        raise ValueError(
            "Recursion too deep (depth={}). Processing {}. Path: {}".format(
                depth, node.key, path_str
            )
        )

    if node.key not in dists or dists[node.key] is not node:
        logger.debug("No need to process this node, it has been removed")
        return

    if node.complete:
        assert node.metadata is not None
        logger.info("Reusing dist %s %s", node.metadata.name, node.metadata.version)
        return

    logger.debug("Processing node %s", node)

    # This node is unsolved, find a candidate from the provided repository `repo`.
    if node.metadata is None:
        spec_req = node.build_constraints()

        spec_name = normalize_project_name(spec_req.name)
        if options.pinned_requirements:
            pin = options.pinned_requirements.get(spec_name, spec_req)
            spec_req = merge_requirements(spec_req, pin)

        # The requirement before any soft pin, which decides whether a failure is
        # the pin's fault.
        unpinned_req = spec_req
        soft_pin = options.soft_pins.get(spec_name)
        if soft_pin is not None:
            spec_req = merge_requirements(spec_req, soft_pin)

        def _no_candidate(no_candidate: bool) -> NoCandidateException:
            if soft_pin is not None and is_possible(unpinned_req):
                return PinConflictException(
                    spec_name, soft_pin, unpinned_req, node, no_candidate
                )
            return NoCandidateException(spec_req)

        if not is_possible(spec_req):
            logger.info("Requirement conflict for %s (%s)", node, spec_req)
            # Try walking back. Some reverse dependency contributed a requirement
            # expression that lead to this node being unsolveable. Instead of attempting
            # to search the full space, find the one that conflicts with the most
            # other reverse dependencies and add a new constraint to keep the same
            # version from being selected.
            # Search the full space is expensive and possibly harmful because of how heavily
            # it must hit remote indices.
            reverse_dep = _get_strictest_reverse_dep(node, soft_pin)
            if (
                reverse_dep is None
                or reverse_dep.metadata is None
                or reverse_dep.metadata.version is None
            ):
                raise _no_candidate(no_candidate=False)

            if _walkback_budget is not None and _walkback_budget <= 0:
                logger.info(
                    "Requirement conflict for %s (%s). Walkback budget exhausted.",
                    node,
                    spec_req,
                )
                ex = _no_candidate(no_candidate=False)
                ex.conflicting_node = node
                ex.walkback_project = reverse_dep.metadata.name
                raise ex

            logger.debug(
                "Conflict detected in %s. Unsolving %s and retrying (walkback remaining %s)",
                node.key,
                reverse_dep.key,
                "unlimited" if _walkback_budget is None else _walkback_budget,
            )

            next_max_downgrade = None if max_downgrade is None else max_downgrade - 1
            next_walkback_budget = (
                None if _walkback_budget is None else _walkback_budget - 1
            )
            new_constraints = [
                parse_requirement(
                    "{}!={}".format(
                        reverse_dep.metadata.name, reverse_dep.metadata.version
                    )
                )
            ]
            do_not_use_version = reverse_dep.metadata.version
            walkback_project = reverse_dep.metadata.name
            bad_dist = req_compile.containers.DistInfo(
                "#donotuse#-{}-{}-{}".format(
                    reverse_dep.key,
                    str(do_not_use_version).replace("-", "_"),
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
                    depth=depth,
                    max_downgrade=next_max_downgrade,
                    _path=tuple(n for n in _path if n != reverse_dep),
                    _walkback_budget=next_walkback_budget,
                )
            except NoCandidateException as ex:
                ex.do_not_use.append(do_not_use_version)
                ex.conflicting_node = node
                ex.walkback_project = walkback_project
                raise
            finally:
                dists.remove_dists(bad_constraint, remove_upstream=False)
            return

        try:
            metadata, cached = repo.get_dist(
                spec_req,
                allow_source_dist=spec_name not in options.only_binary,
                max_downgrade=max_downgrade,
            )
        except NoCandidateException:
            if soft_pin is None:
                raise
            # The pin is only at fault if the requirement is solvable without it.
            repo.get_dist(
                unpinned_req,
                allow_source_dist=spec_name not in options.only_binary,
                max_downgrade=max_downgrade,
            )
            raise _no_candidate(no_candidate=True) from None
        logger.debug(
            "Acquired candidate %s %s [%s] (%s)",
            metadata,
            spec_req,
            metadata.origin,
            "cached" if cached else "download",
        )

        # Add extras to the "reason" if the commandline option was specified.
        # This only applies to sourcd repositories.
        reason: Optional[packaging.requirements.Requirement] = None
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
                        reason.name + "[" + ",".join(options.extras) + "]"
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
        elif not dep.complete:
            compile_roots(
                dep,
                node,
                repo,
                dists,
                options,
                depth=depth + 1,
                max_downgrade=max_downgrade,
                _path=_path + (node,),
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
    target: Optional[TargetEnvironment] = None,
    pins: Optional[Mapping[NormName, packaging.requirements.Requirement]] = None,
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
        target: The environment to compile for. Defaults to the target of `repo`, which
            itself defaults to the host.
        pins: Soft pins keyed by normalized name. Unlike constraints, a soft pin
            never requires a package, is not recorded in the solution and yields
            when the package cannot satisfy it: `PinConflictException` is raised
            instead of resolving the dependents differently. See
            `CompileOptions.soft_pins`.

    Returns:
        the solution and root nodes used to generate it
    """
    if target is None:
        target = repo.target
    results = req_compile.dists.DistributionCollection(target=target)

    constraint_nodes = set()
    nodes = set()
    all_pinned = True
    pinned_requirements: Dict[NormName, packaging.requirements.Requirement] = {}

    if constraint_reqs is not None:
        for constraint_source in constraint_reqs:
            all_pinned &= all([is_pinned_requirement(req) for req in constraint_source])
            if all_pinned:
                for req in constraint_source:
                    pinned_requirements[normalize_project_name(req.name)] = req

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
    options.soft_pins = dict(pins or {})

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
                if not node.complete:
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


def _soft_pins(
    agreed: Mapping[NormName, packaging.version.Version],
    rejected: Mapping[NormName, Sequence[Rejection]],
) -> Dict[NormName, packaging.requirements.Requirement]:
    """The soft pins keeping solutions compiled together aligned.

    A project with an agreed version is pinned to it. A project without one, whose
    versions some solution rejected, is kept away from those versions.
    """
    pins = {}
    for name, version in agreed.items():
        pins[name] = parse_requirement(f"{name}=={version}")
    for name, rejections in rejected.items():
        if name in agreed or not rejections:
            continue
        pins[name] = parse_requirement(
            name + ",".join(f"!={rejection.version}" for rejection in rejections)
        )
    return pins


def perform_compile_group(
    input_reqs: Iterable[RequirementContainer],
    repos: Sequence[Repository],
    constraint_reqs: Optional[Iterable[RequirementContainer]] = None,
    remove_constraints: bool = False,
    extras: Optional[Iterable[str]] = None,
    allow_circular_dependencies: bool = True,
    only_binary: Optional[Set[NormName]] = None,
    max_downgrade: Optional[int] = None,
    pins: Optional[Mapping[NormName, packaging.version.Version]] = None,
    max_passes: int = MAX_GROUP_PASSES,
) -> List[Tuple[DistributionCollection, Set[DependencyNode]]]:
    """Compile the same requirements for several targets, with one version per project.

    Each repository is compiled for its own target, in order. A project keeps the
    version the first target that needs it resolves it to, so the solutions never
    disagree. When a later target cannot use that version at all, e.g. there is no
    artifact for its platform or its dependencies require another version, the
    version is rejected for every target and the group is compiled again, until a
    pass completes without any rejection. A target may also resolve the dependents
    of a pinned project to other versions than an earlier target did rather than
    reject the version, in which case the next pass aligns the earlier target.

    Args:
        input_reqs: The requirements, shared by every target.
        repos: One repository per target, compiled in this order. Each compiles for
            its own target, see `Repository.target`.
        constraint_reqs: Constraints to use when compiling.
        remove_constraints: Whether to remove the constraints from the solutions.
        extras: Extras to apply automatically to source projects.
        allow_circular_dependencies: Whether to allow circular dependencies.
        only_binary: Set of projects that should only consider binary distributions.
        max_downgrade: The maximum number of version downgrades that will be allowed
            for conflicts, and the maximum number of versions of a project the
            targets may reject before giving up.
        pins: Versions to start from, keyed by normalized name, e.g. those of the
            solutions being recompiled. They are soft pins: a project is only pinned
            if it is required, and a version that a target cannot use is rejected
            like any other.
        max_passes: The maximum number of times the group is compiled.

    Returns:
        The solution and root nodes of each repository, in the order given.

    Raises:
        NoCommonVersionException: If no version of a project can be used by every
            target that needs it.
        NoCandidateException: If the requirements cannot be resolved for a target.
    """
    input_reqs = list(input_reqs)
    if max_downgrade is None:
        max_downgrade = MAX_DOWNGRADE
    agreed: Dict[NormName, packaging.version.Version] = dict(pins or {})
    rejected: Dict[NormName, List[Rejection]] = defaultdict(list)
    last: Optional[Rejection] = None

    for _ in range(max_passes):
        rejections = 0
        results: List[Tuple[DistributionCollection, Set[DependencyNode]]] = []
        for repo in repos:
            target = repo.target
            while True:
                try:
                    results.append(
                        perform_compile(
                            input_reqs,
                            repo,
                            constraint_reqs=constraint_reqs,
                            remove_constraints=remove_constraints,
                            extras=extras,
                            allow_circular_dependencies=allow_circular_dependencies,
                            only_binary=only_binary,
                            max_downgrade=max_downgrade,
                            target=target,
                            pins=_soft_pins(agreed, rejected),
                        )
                    )
                    break
                except PinConflictException as ex:
                    rejections += 1
                    version = agreed.pop(ex.name, None)
                    rejected[ex.name].append(Rejection(target, version, ex))
                    if version is None or len(rejected[ex.name]) > max_downgrade:
                        # Every version this target can use was rejected by
                        # another, or the search is not converging.
                        raise NoCommonVersionException(
                            ex.name, rejected[ex.name]
                        ) from ex
                    LOG.info(
                        "%s cannot use %s (%s), resolving it again for every target",
                        target.name,
                        ex.pin,
                        ex,
                    )
                    last = rejected[ex.name][-1]

            for node in results[-1][0]:
                if (
                    node.metadata is None
                    or node.metadata.meta
                    or node.metadata.version is None
                ):
                    continue
                version = agreed.setdefault(node.key, node.metadata.version)
                assert (
                    version == node.metadata.version
                ), f"{target.name} resolved {node.key} to {node.metadata.version}, not {version}"

        if not rejections:
            return results

    # Every pass rejected a version, so there is a last rejection to report.
    assert last is not None
    LOG.error(
        "The solutions still disagree after %d passes. REQ_COMPILE_MAX_GROUP_PASSES "
        "raises the limit.",
        max_passes,
    )
    raise NoCommonVersionException(last.cause.name, rejected[last.cause.name])


def _add_constraints(
    all_pinned: bool,
    constraint_reqs: Optional[Iterable[RequirementContainer]],
    results: DistributionCollection,
) -> None:
    if all_pinned and constraint_reqs is not None:
        for constraint_source in constraint_reqs:
            results.add_dist(constraint_source, None, None)
