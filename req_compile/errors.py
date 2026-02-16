"""Errors describing problems that can occur when extracting metadata"""

from typing import TYPE_CHECKING, Any, Optional

import packaging.requirements
import packaging.version

if TYPE_CHECKING:
    from req_compile.dists import DependencyNode


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
