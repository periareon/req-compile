from __future__ import print_function

import os
import sys
from typing import Any, Iterable, Optional, Sequence, Tuple

import pkg_resources
from overrides import overrides

import req_compile.containers
import req_compile.dists
import req_compile.utils
from req_compile.containers import RequirementContainer
from req_compile.dists import DependencyNode, DistributionCollection
from req_compile.errors import NoCandidateException
from req_compile.repos import RepositoryInitializationError
from req_compile.repos.repository import Candidate, DistributionType, Repository
from req_compile.repos.source import ReferenceSourceRepository


def _candidate_from_node(node: DependencyNode) -> Candidate:
    assert node.metadata is not None
    if node.metadata.version is None:
        raise ValueError(f"No version given for {node.key}")

    candidate = Candidate(
        node.key,
        None,
        node.metadata.version,
        None,
        None,
        "any",
        None,
        DistributionType.SOURCE,
    )
    candidate.preparsed = node.metadata
    return candidate


class SolutionRepository(Repository):
    """A repository that provides distributions from a previous solution."""

    def __init__(self, filename: str, excluded_packages: Iterable[str] = None) -> None:
        """Constructor."""
        super(SolutionRepository, self).__init__("solution", allow_prerelease=True)
        self.filename = os.path.abspath(filename) if filename != "-" else "-"
        self.excluded_packages = excluded_packages or []
        if excluded_packages:
            self.excluded_packages = [
                req_compile.utils.normalize_project_name(pkg)
                for pkg in excluded_packages
            ]

        # Partial line when parsing requirements files with multiline
        # hashes
        self._partial_line = ""

        if os.path.exists(filename) or self.filename == "-":
            self.load_from_file(self.filename)
        else:
            self.solution = DistributionCollection()

    def __repr__(self) -> str:
        return "--solution {}".format(self.filename)

    def __eq__(self, other: Any) -> bool:
        return (
            isinstance(other, SolutionRepository)
            and super(SolutionRepository, self).__eq__(other)
            and self.filename == other.filename
        )

    def __hash__(self) -> int:
        return hash("solution") ^ hash(self.filename)

    @overrides
    def get_candidates(
        self, req: Optional[pkg_resources.Requirement]
    ) -> Sequence[Candidate]:
        if req is None:
            return [_candidate_from_node(node) for node in self.solution]

        if (
            req_compile.utils.normalize_project_name(req.project_name)
            in self.excluded_packages
        ):
            return []

        try:
            node = self.solution[req.project_name]
            candidate = _candidate_from_node(node)
            return [candidate]
        except KeyError:
            return []

    @overrides
    def resolve_candidate(
        self, candidate: Candidate
    ) -> Tuple[RequirementContainer, bool]:
        if candidate.preparsed is None:
            raise NoCandidateException(
                req_compile.utils.parse_requirement(candidate.name)
            )
        return candidate.preparsed, True

    @overrides
    def close(self) -> None:
        pass

    def load_from_file(self, filename: str) -> None:
        self.solution = req_compile.dists.DistributionCollection()

        if filename == "-":
            reqfile = sys.stdin
        else:
            reqfile = open(filename, encoding="utf-8")

        try:
            self._load_from_lines(reqfile.readlines(), meta_file=filename)
        finally:
            if reqfile is not sys.stdin:
                reqfile.close()

        self._remove_nodes()

    def _load_from_lines(self, lines: Iterable[str], meta_file: str = None) -> None:
        for line in lines:
            # Skip directives we don't process in solutions (like --index-url)
            if line.strip().startswith("--") and not self._partial_line:
                continue
            self._parse_line(line, meta_file)
        if self._partial_line:
            self._parse_multi_line("", meta_file)

    def _remove_nodes(self) -> None:
        nodes_to_remove = []
        missing_ver = req_compile.utils.parse_version("0+missing")
        for node in self.solution:
            if node.metadata is None or node.metadata.version == missing_ver:
                nodes_to_remove.append(node)
        for node in nodes_to_remove:
            try:
                del self.solution.nodes[node.key]
            except KeyError:
                pass

    def _parse_line(self, line: str, meta_file: str = None) -> None:
        if self._partial_line:
            self._parse_multi_line(line, meta_file)
            return

        req_part, has_comment, _ = line.partition("#")
        req_part = req_part.strip()
        if not req_part:
            return

        # Is the last non-comment character a line break? If so treat this as
        # a multi-line entry.
        if not has_comment or req_part[-1] == "\\":
            self._parse_multi_line(line, meta_file)
            return

        self._parse_single_line(line)

    def _parse_single_line(self, line: str, meta_file: str = None) -> None:
        req_hash_part, _, source_part = line.partition("#")
        req_hash_part = req_hash_part.strip()
        if not req_hash_part:
            return

        hashes = req_hash_part.split("--hash=")
        req_part = hashes[0]

        req = req_compile.utils.parse_requirement(req_part)

        if (
            not source_part.strip()
            or "#" in source_part
            or source_part.startswith(" via")
        ):
            parts = source_part.strip().split("#")
            in_sources = False
            sources = []
            for part in parts:
                part = part.strip()

                if in_sources:
                    sources.append(part)
                    continue

                if part.startswith("via"):
                    if part != "via":
                        sources.append(part[4:])
                    in_sources = True

            if not sources:
                raise RepositoryInitializationError(
                    SolutionRepository,
                    "Solution file {} is not fully annotated and cannot be used. Consider"
                    " compiling the solution against a remote index to add annotations.".format(
                        meta_file
                    ),
                )
        else:
            # Strip of the repository index if --annotate was used.
            source_part = source_part.strip()
            if source_part[0] == "[":
                _, _, source_part = source_part.partition("] ")
            sources = source_part.split(", ")

        dist_hash: Optional[str] = None
        if len(hashes) > 1:
            dist_hash = hashes[1]
            if len(hashes) > 2:
                self.logger.debug("Discarding %d hashes, using first", len(hashes) - 2)

        try:
            self._add_sources(req, sources, dist_hash=dist_hash)
        except Exception:
            raise ValueError(f"Failed to parse line: {line}")

    def _parse_multi_line(self, line: str, meta_file: str = None) -> None:
        stripped_line = line.strip()
        stripped_line = stripped_line.rstrip("\\")

        # Is this the start of a new requirement, or the end of the document?
        if self._partial_line and (
            not stripped_line or not stripped_line.startswith(("#", "--"))
        ):
            self._parse_single_line(self._partial_line, meta_file=meta_file)
            self._partial_line = ""

        self._partial_line += stripped_line

    def _add_sources(
        self,
        req: pkg_resources.Requirement,
        sources: Iterable[str],
        dist_hash: str = None,
    ) -> None:
        pkg_names = map(lambda x: x.split(" ")[0], sources)
        constraints = map(
            lambda x: x.split(" ")[1].replace("(", "").replace(")", "")
            if "(" in x
            else None,
            sources,
        )
        version = req_compile.utils.parse_version(list(req.specs)[0][1])

        metadata = None
        if req.project_name in self.solution:
            metadata = self.solution[req.project_name].metadata
        if metadata is None:
            metadata = req_compile.containers.DistInfo(req.name, version, [])

        metadata.hash = dist_hash

        metadata.version = version
        metadata.origin = self
        self.solution.add_dist(metadata, None, req)
        for name, constraint in zip(pkg_names, constraints):
            if name and not (
                name.endswith(".txt")
                or name.endswith(".out")
                or "\\" in name
                or "/" in name
            ):
                constraint_req = None

                try:
                    constraint_req = req_compile.utils.parse_requirement(name)
                    # Use .name instead of .project_name to avoid normalization
                    proj_name = constraint_req.name
                except ValueError:
                    proj_name = name

                self.solution.add_dist(proj_name, None, constraint_req)
                reverse_dep = self.solution[name]
                if reverse_dep.metadata is None:
                    inner_meta = req_compile.containers.DistInfo(
                        proj_name,
                        req_compile.utils.parse_version("0+missing"),
                        [],
                    )
                    inner_meta.origin = ReferenceSourceRepository(inner_meta)
                    reverse_dep.metadata = inner_meta
            else:
                reverse_dep = None
            reason = _create_metadata_req(req, metadata, name, constraint)
            if reverse_dep is not None:
                assert reverse_dep.metadata is not None
                reverse_dep.metadata.reqs.append(reason)
            self.solution.add_dist(metadata.name, reverse_dep, reason)


def _create_metadata_req(
    req: pkg_resources.Requirement,
    metadata: RequirementContainer,
    name: str,
    constraints: Optional[str],
) -> pkg_resources.Requirement:
    marker = ""
    if "[" in name:
        extra = next(iter(req_compile.utils.parse_requirement(name).extras))
        marker = ' ; extra == "{}"'.format(extra)

    return req_compile.utils.parse_requirement(
        "{}{}{}{}".format(
            metadata.name,
            ("[" + ",".join(req.extras) + "]") if req.extras else "",
            constraints if constraints else "",
            marker,
        )
    )
