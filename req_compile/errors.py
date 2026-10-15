"""Errors describing problems that can occur when extracting metadata"""

from typing import TYPE_CHECKING, Any, List, NamedTuple, Optional

import packaging.requirements
import packaging.version

from req_compile.utils import NormName

if TYPE_CHECKING:
    from req_compile.dists import DependencyNode
    from req_compile.target import TargetEnvironment


class ExceptionWithDetails(Exception):
    def __init__(self) -> None:
        super(ExceptionWithDetails, self).__init__()
        self.results: Optional[Any] = None


class MetadataError(ExceptionWithDetails):
    def __init__(
        self, name: str, version: Optional[packaging.version.Version], ex: Exception
    ) -> None:
        super(MetadataError, self).__init__()
        self.name = name
        self.version = version
        self.ex = ex

    def __str__(self) -> str:
        return "Failed to parse metadata for package {} ({}) - {}: {}".format(
            self.name, self.version, self.ex.__class__.__name__, str(self.ex)
        )


class NoCandidateException(ExceptionWithDetails):
    def __init__(
        self, req: packaging.requirements.Requirement, results: Any = None
    ) -> None:
        super(NoCandidateException, self).__init__()
        self.req = req
        self.results = results
        self.check_level = 0
        # List of versions marked do not use because they produce conflicts with other deps.
        self.do_not_use: list[packaging.version.Version] = []
        # Node that conflicted with this req, if applicable.
        self.conflicting_node: Optional["DependencyNode"] = None
        # Project name that was walked back, if applicable.
        self.walkback_project: Optional[str] = None

    def __str__(self) -> str:
        if self.req.specifier:
            return 'NoCandidateException - no candidate for "{}" satisfies {}'.format(
                self.req.name, self.req.specifier
            )
        return 'NoCandidateException - no candidates found for "{}"'.format(
            self.req.name
        )


class PinConflictException(NoCandidateException):
    """A soft pin could not be honored for a requirement that is otherwise solvable.

    Raised in place of `NoCandidateException` when the requirement without the
    pin can be satisfied, so the caller can lift the pin and resolve again. See
    `CompileOptions.soft_pins`.
    """

    def __init__(
        self,
        name: NormName,
        pin: packaging.requirements.Requirement,
        req: packaging.requirements.Requirement,
        node: "DependencyNode",
        no_candidate: bool,
    ) -> None:
        """
        Args:
            name: The normalized name of the pinned project.
            pin: The soft pin that could not be honored.
            req: The requirement without the pin, as the reverse dependencies and
                hard pins constrain it.
            node: The node the pin applies to.
            no_candidate: True when the pin conflicts with nothing but no candidate
                satisfies it, e.g. the pinned version has no artifact for the
                target. False when the pin conflicts with `req`.
        """
        super().__init__(req)
        self.name = name
        self.pin = pin
        self.node = node
        self.no_candidate = no_candidate

    def __str__(self) -> str:
        if self.no_candidate:
            return f"no candidate for {self.pin}"
        return f"{self.pin} conflicts with {self.req}"


class Rejection(NamedTuple):
    """A version of a project that one of the solutions compiled together cannot use."""

    target: "TargetEnvironment"
    # The version the other solutions had agreed on, or None if none had and the
    # target cannot use any version left after the earlier rejections.
    version: Optional[packaging.version.Version]
    cause: PinConflictException


class NoCommonVersionException(ExceptionWithDetails):
    """Solutions compiled together cannot agree on the version of a project."""

    def __init__(self, name: NormName, rejections: List[Rejection]) -> None:
        """
        Args:
            name: The normalized name of the project.
            rejections: The versions some target could not use, in the order they
                were rejected, ending with the failure that stopped the search.
        """
        super().__init__()
        self.name = name
        self.rejections = list(rejections)

    def __str__(self) -> str:
        lines = [f"No version of {self.name} can be used by every solution:"]
        for rejection in self.rejections:
            if rejection.version is None:
                lines.append(f"  {rejection.target.name}: {rejection.cause}")
            else:
                lines.append(
                    f"  {rejection.target.name} cannot use "
                    f"{self.name}=={rejection.version}: {rejection.cause}"
                )
        return "\n".join(lines)
