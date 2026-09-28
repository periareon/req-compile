import collections
import os
import sys
from pathlib import Path
from typing import Any, DefaultDict, Iterable, Optional, Sequence, Set, Tuple, Union

import packaging.requirements
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
from req_compile.utils import NormName, normalize_project_name


def _candidate_from_node(node: DependencyNode) -> Candidate:
    assert node.metadata is not None
    if node.metadata.version is None:
        raise ValueError(f"No version given for {node.key}")

    return node.metadata.candidate


class SolutionRepository(Repository):
    """A repository that provides distributions from a previous solution."""

    def __init__(
        self,
        filename: Union[str, Path],
        excluded_packages: Optional[Iterable[str]] = None,
    ) -> None:
        """Constructor."""
        super(SolutionRepository, self).__init__("solution", allow_prerelease=True)
        self.filename = os.path.abspath(filename) if str(filename) != "-" else "-"
        self.excluded_packages = excluded_packages or []
        if excluded_packages:
            self.excluded_packages = [
                req_compile.utils.normalize_project_name(pkg)
                for pkg in excluded_packages
            ]

        # Partial line when parsing requirements files with multiline
        # hashes
        self._partial_line = ""

        # The extras each project was solved with, gathered from the annotations
        # in the solution. A solution only describes the requirements of the
        # extras that were active when it was compiled.
        self._known_extras: DefaultDict[NormName, Set[NormName]] = (
            collections.defaultdict(set)
        )

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
        self, req: Optional[packaging.requirements.Requirement]
    ) -> Sequence[Candidate]:
        if req is None:
            return [_candidate_from_node(node) for node in self.solution]

        if req_compile.utils.normalize_project_name(req.name) in self.excluded_packages:
            return []

        try:
            node = self.solution[req.name]
        except KeyError:
            return []

        # The solution only describes the extras it was compiled with. If more are
        # being asked for now, this repository cannot say what they require, so it
        # must defer to a repository holding the complete metadata.
        if (
            req.extras
            and node.metadata is not None
            and not node.metadata.describes_extras(req.extras)
        ):
            self.logger.debug(
                "%s is in the solution but it does not describe the extras %s",
                req.name,
                ",".join(sorted(req.extras)),
            )
            return []

        return [_candidate_from_node(node)]

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
        # The extras are gathered while parsing and only describe the solution
        # being loaded now, so nothing from a previously loaded file may survive.
        self._partial_line = ""
        self._known_extras.clear()

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

    def _load_from_lines(
        self, lines: Iterable[str], meta_file: Optional[str] = None
    ) -> None:
        for line in lines:
            # Skip directives we don't process in solutions (like --index-url)
            if line.strip().startswith("--") and not self._partial_line:
                continue
            self._parse_line(line, meta_file)
        if self._partial_line:
            self._parse_multi_line("", meta_file)

        self._apply_known_extras()

    def _apply_known_extras(self) -> None:
        """Mark each solved distribution with the extras this solution describes.

        This runs once the whole solution has been read, because a project can be
        referenced with an extra before the line that pins it is parsed.
        """
        for node in self.solution:
            if node.metadata is not None:
                # Copy, so that the metadata keeps describing this solution even if
                # another one is loaded into this repository later.
                node.metadata.known_extras = set(self._known_extras[node.key])

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

    def _parse_line(self, line: str, meta_file: Optional[str] = None) -> None:
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

    def _parse_single_line(self, line: str, meta_file: Optional[str] = None) -> None:
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
            in_url = False
            url = ""
            sources = []
            for part in parts:
                part = part.strip()
                if part.startswith(("http://", "https://")) or part.endswith(
                    (".whl", ".gz", ".tgz", ".zip", ".tar", ".bz2")
                ):
                    in_url = True
                    in_sources = False
                    url = part
                elif in_url:
                    url += "#" + part
                    in_url = False

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
            url = ""

        dist_hash: Optional[str] = None
        if len(hashes) > 1:
            dist_hash = hashes[1]
            if len(hashes) > 2:
                self.logger.debug("Discarding %d hashes, using first", len(hashes) - 2)

        try:
            self._add_sources(
                req, sources, url=url if url else None, dist_hash=dist_hash
            )
        except Exception as ex:
            raise ValueError(f"Failed to parse line: {line}") from ex

    def _parse_multi_line(self, line: str, meta_file: Optional[str] = None) -> None:
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
        req: packaging.requirements.Requirement,
        sources: Iterable[str],
        url: Optional[str] = None,
        dist_hash: Optional[str] = None,
    ) -> None:
        pkg_names = map(lambda x: x.split(" ", 1)[0], sources)
        constraints = map(
            lambda x: (
                x.split(" ", 1)[1].replace("(", "").replace(")", "")
                if "(" in x
                else None
            ),
            sources,
        )
        version = req_compile.utils.parse_version(next(iter(req.specifier)).version)

        # Record this project even when no extras are involved, so that a solution
        # that describes no extras for it is distinguishable from one that was
        # never asked about it at all.
        known_extras = self._known_extras[normalize_project_name(req.name)]
        known_extras.update(normalize_project_name(extra) for extra in req.extras)

        metadata = None
        if req.name in self.solution:
            metadata = self.solution[req.name].metadata
        if metadata is None:
            metadata = req_compile.containers.DistInfo(req.name, version, [])

        metadata.hash = dist_hash

        metadata.version = version
        metadata.origin = self

        candidate = Candidate(
            req.name,
            None,
            version,
            None,
            None,
            "any",
            (None, url),
            DistributionType.SOURCE,
        )
        candidate.preparsed = metadata
        metadata.candidate = candidate

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
                    proj_name = constraint_req.name
                except ValueError:
                    proj_name = name

                if constraint_req is not None:
                    # `name` can be written as `project[extra]`, which tells us
                    # the solution knows what that extra of `project` requires.
                    self._known_extras[normalize_project_name(proj_name)].update(
                        normalize_project_name(extra) for extra in constraint_req.extras
                    )

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
            # The reason carries the extras of this project that its reverse
            # dependency asked for, e.g. `pyspnego==0.9.2  # foo (>=0.9.2 [kerberos])`.
            known_extras.update(
                normalize_project_name(extra) for extra in reason.extras
            )
            if reverse_dep is not None:
                assert reverse_dep.metadata is not None
                reverse_dep.metadata.reqs.append(reason)
            self.solution.add_dist(metadata.name, reverse_dep, reason)


def _create_metadata_req(
    req: packaging.requirements.Requirement,
    metadata: RequirementContainer,
    name: str,
    constraints: Optional[str],
) -> packaging.requirements.Requirement:
    marker = ""
    if "[" in name:
        # The reverse dependency can be annotated with more than one of its extras,
        # e.g. `child==1  # parent[x1,x2]`, meaning any of them pulls in this
        # requirement. All of them have to be reconstructed, otherwise a later
        # compilation asking for one of the omitted extras would drop this
        # requirement even though the solution does describe it.
        source_extras = sorted(req_compile.utils.parse_requirement(name).extras)
        if source_extras:
            marker = " ; " + " or ".join(
                'extra == "{}"'.format(extra) for extra in source_extras
            )

    # req will only have extras if the solution file had them in the left-hand
    # side of == expression, e.g. req[extra]==1.0.  Since pip doesn't support having
    # extras on the left-hand side for constraints files, we don't emit this
    # any longer.
    extras = req.extras
    if constraints and ("[" in constraints and "]" in constraints):
        # Parse out the extras that brought in this requirement. It will look like
        # (>1.0 [extra1,extra2]). Usually it would just be one unless the distribution
        # includes a requirement under multiple extras.
        constraints, extra_string = constraints.split("[", 1)
        constraints = constraints.strip()
        extra_string = extra_string.replace("]", "")
        extras = {extra.strip() for extra in extra_string.split(",")}

    return req_compile.utils.parse_requirement(
        "{}{}{}{}".format(
            metadata.name,
            ("[" + ",".join(sorted(extras)) + "]") if extras else "",
            constraints if constraints else "",
            marker,
        )
    )
