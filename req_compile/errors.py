"""Errors describing problems that can occur when extracting metadata"""

from typing import Any, Optional

import packaging.version
import pkg_resources

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
    def __init__(self, req: pkg_resources.Requirement, results: Any = None) -> None:
        super(NoCandidateException, self).__init__()
        self.req = req
        self.results = results
        self.check_level = 0
        # List of versions marked do not use because they produce conflicts with other deps.
        self.do_not_use: list[packaging.version.Version] = []
        # Node that conflicted with this req, if applicable.
        self.conflicting_node: Optional[Any] = None
        # Project name that was walked back, if applicable.
        self.walkback_project: Optional[str] = None

    def __str__(self) -> str:
        if self.req.specifier:
            return 'NoCandidateException - no candidate for "{}" satisfies {}'.format(
                self.req.project_name, self.req.specifier
            )
        return 'NoCandidateException - no candidates found for "{}"'.format(
            self.req.project_name
        )
