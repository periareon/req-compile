from __future__ import annotations

import collections.abc
import itertools
import logging
import sys
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set, Union

import pkg_resources

from req_compile.containers import RequirementContainer
from req_compile.repos import Repository
from req_compile.utils import (
    NormName,
    merge_requirements,
    normalize_project_name,
    parse_requirement,
)


class DependencyNode:
    """
    Class representing a node in the dependency graph of a resolution. Contains information
    about whether or not this node has a solution yet -- meaning, is it resolved to a
    concrete requirement resolved from a Repository
    """

    def __init__(self, key: NormName, metadata: Optional[RequirementContainer]) -> None:
        self.key = key
        self.metadata = metadata
        self.dependencies: Dict[
            DependencyNode, Optional[pkg_resources.Requirement]
        ] = {}
        self.reverse_deps: Set[DependencyNode] = set()
        self.repo: Optional[Repository] = None
        self.complete = (
            False  # Whether this node and all of its dependency are completely solved
        )

    def __repr__(self) -> str:
        return self.key

    def __hash__(self) -> int:
        return hash(self.key)

    def __str__(self) -> str:
        if self.metadata is None:
            return self.key + " [UNSOLVED]"
        if self.metadata.meta:
            return self.metadata.name
        return "==".join(str(x) for x in self.metadata.to_definition(self.extras))

    def __lt__(self, other: Any) -> bool:
        return self.key < other.key

    @property
    def extras(self) -> Set[str]:
        """Extras for this node that its reverse dependencies have requested."""
        extras = set()
        for rdep in self.reverse_deps:
            assert (
                rdep.metadata is not None
            ), "Reverse dependency should already have a solution"
            reason = rdep.dependencies[self]
            if reason is not None:
                extras |= set(reason.extras)
        return extras

    def add_reason(
        self, node: DependencyNode, reason: Optional[pkg_resources.Requirement]
    ) -> None:
        self.dependencies[node] = reason

    def build_constraints(self) -> pkg_resources.Requirement:
        result = None

        for rdep_node in self.reverse_deps:
            assert (
                rdep_node.metadata is not None
            ), "Reverse dependency should already have a solution"
            all_reqs = set(rdep_node.metadata.requires())
            for extra in rdep_node.extras:
                all_reqs |= set(rdep_node.metadata.requires(extra=extra))
            for req in all_reqs:
                if normalize_project_name(req.project_name) == self.key:
                    result = merge_requirements(result, req)

        if result is None:
            if self.metadata is None:
                result = parse_requirement(self.key)
            else:
                result = parse_requirement(self.metadata.name)
            assert result is not None

            if self.extras:
                result.extras = self.extras
                # Reparse to create a correct hash
                result = parse_requirement(str(result))
                assert result is not None
        return result


def build_explanation(root_node: DependencyNode) -> collections.abc.Collection[str]:
    """Build an explanation for why a node was included in the solution.

    The explanation provides the version constraints supplied by the reverse
    dependencies for this node.
    """
    constraints: List[str] = []
    for node in root_node.reverse_deps:
        assert (
            node.metadata is not None
        ), "Reverse dependency should already have a solution"
        all_reqs = set(node.metadata.requires())
        for extra in node.extras:
            all_reqs |= set(node.metadata.requires(extra=extra))
        for req in all_reqs:
            if normalize_project_name(req.project_name) == root_node.key:
                constraints.append(_process_constraint_req(req, node))
    return constraints


def _process_constraint_req(
    req: pkg_resources.Requirement, node: DependencyNode
) -> str:
    assert node.metadata is not None, "Node {} must be solved".format(node)
    extras: Set[str] = set()
    # Determine which extras, if any, were the reason this req was included.
    if req.marker:
        for marker in req.marker._markers:  # pylint: disable=protected-access
            if (
                isinstance(marker, tuple)
                and marker[0].value == "extra"
                and marker[1].value == "=="
            ):
                extras.add(marker[2].value.strip().lower())
    source = node.metadata.name + (
        ("[" + ",".join(sorted(extras)) + "]") if extras else ""
    )

    specifics = ""
    if req.specifier:  # type: ignore[attr-defined]
        specifics = str(req.specifier)  # type: ignore[attr-defined]

    # Determine which extras this req was itself requesting.
    if req.extras:
        specifics += (
            f" [{','.join(sorted(extra.strip().lower() for extra in req.extras))}]"
        )

    if specifics:
        specifics = f" ({specifics.strip()})"
    return source + specifics


class DistributionCollection:
    """A collection of dependencies and their distributions. This is the main representation
    of the graph of dependencies when putting together a resolution. As distributions are
    added to the collection and provide a concrete RequirementContainer (like a DistInfo from
    a wheel), the corresponding node in this collection will be marked solved."""

    def __init__(self) -> None:
        self.nodes: Dict[NormName, DependencyNode] = {}
        self.logger = logging.getLogger("req_compile.dists")

    @staticmethod
    def _build_key(name: str) -> NormName:
        return normalize_project_name(name)

    def add_dist(
        self,
        name_or_metadata: Union[str, RequirementContainer],
        source: Optional[DependencyNode],
        reason: Optional[pkg_resources.Requirement],
    ) -> Set[DependencyNode]:
        """Add a distribution as a placeholder or as a solution.

        Args:
            name_or_metadata: Distribution info to add, or if it is unknown, the
                name of the distribution, so it can be added as a placeholder.
            source: The source of the distribution. This is used to build the graph.
            reason: The requirement that caused this distribution to be added to the
                graph. This is used to constrain which solutions will be allowed.
        """
        self.logger.debug("Adding dist: %s %s %s", name_or_metadata, source, reason)

        if isinstance(name_or_metadata, str):
            req_name = name_or_metadata
            metadata_to_apply: Optional[RequirementContainer] = None
        else:
            assert isinstance(name_or_metadata, RequirementContainer)
            metadata_to_apply = name_or_metadata
            req_name = metadata_to_apply.name

        key = DistributionCollection._build_key(req_name)

        if key in self.nodes:
            node = self.nodes[key]
        else:
            node = DependencyNode(key, metadata_to_apply)
            self.nodes[key] = node

        # If a new extra is being supplied, update the metadata
        if (
            reason
            and node.metadata
            and reason.extras
            and set(reason.extras) - node.extras
        ):
            metadata_to_apply = node.metadata
            node.complete = False

        if source is not None and source.key in self.nodes:
            node.reverse_deps.add(source)
            source.add_reason(node, reason)

        nodes = set()
        if metadata_to_apply is not None:
            nodes |= self._update_dists(node, metadata_to_apply)

        self._discard_metadata_if_necessary(node, reason)

        if node.key not in self.nodes:
            raise ValueError("The node {} is gone, while adding".format(node.key))

        return nodes

    def _discard_metadata_if_necessary(
        self, node: DependencyNode, reason: Optional[pkg_resources.Requirement]
    ) -> None:
        if node.metadata is not None and not node.metadata.meta and reason is not None:
            if node.metadata.version is not None and not reason.specifier.contains(
                node.metadata.version, prereleases=True
            ):
                self.logger.debug(
                    "Existing solution (%s) invalidated by %s", node.metadata, reason
                )
                # Discard the metadata
                self.remove_dists(node, remove_upstream=False)

    def _update_dists(
        self, node: DependencyNode, metadata: RequirementContainer
    ) -> Set[DependencyNode]:
        node.metadata = metadata
        add_nodes = {node}
        for extra in {None} | node.extras:
            for req in metadata.requires(extra):
                # This adds a placeholder entry
                add_nodes |= self.add_dist(req.name, node, req)
        return add_nodes

    def remove_dists(
        self,
        node: Union[DependencyNode, Iterable[DependencyNode]],
        remove_upstream: bool = True,
    ) -> None:
        if isinstance(node, collections.abc.Iterable):
            for single_node in node:
                self.remove_dists(single_node, remove_upstream=remove_upstream)
            return

        self.logger.info("Removing dist(s): %s (upstream = %s)", node, remove_upstream)

        if node.key not in self.nodes:
            self.logger.debug("Node %s was already removed", node.key)
            return

        if remove_upstream:
            del self.nodes[node.key]
            for reverse_dep in node.reverse_deps:
                del reverse_dep.dependencies[node]

        for dep in node.dependencies:
            if remove_upstream or dep.key != node.key:
                dep.reverse_deps.remove(node)
                if not dep.reverse_deps:
                    self.remove_dists(dep)

        if not remove_upstream:
            node.dependencies = {}
            node.metadata = None
            node.complete = False

    def visit_nodes(
        self,
        roots: Iterable[DependencyNode],
        max_depth: int = sys.maxsize,
        reverse: bool = False,
        _visited: Optional[Set[DependencyNode]] = None,
        _cur_depth: int = 0,
    ) -> Iterable[DependencyNode]:
        if _visited is None:
            _visited = set()

        if _cur_depth == max_depth:
            return _visited

        if reverse:
            next_nodes: Iterable[DependencyNode] = itertools.chain(
                *[root.reverse_deps for root in roots]
            )
        else:
            next_nodes = set()
            for root in roots:
                next_nodes |= set(root.dependencies.keys())

        for node in next_nodes:
            if node in _visited:
                continue

            _visited.add(node)

            self.visit_nodes(
                [node],
                reverse=reverse,
                max_depth=max_depth,
                _visited=_visited,
                _cur_depth=_cur_depth + 1,
            )
        return _visited

    def __contains__(self, project_name: str) -> bool:
        req_name = project_name.split("[")[0]
        return normalize_project_name(req_name) in self.nodes

    def __iter__(self) -> Iterator[DependencyNode]:
        return iter(self.nodes.values())

    def __getitem__(self, project_name: str) -> DependencyNode:
        req_name = project_name.split("[")[0]
        return self.nodes[normalize_project_name(req_name)]
