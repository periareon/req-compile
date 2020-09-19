"""Errors describing problems that can occur when extracting metadata"""
from typing import Any, Optional


class ExceptionWithDetails(Exception):
    def __init__(self):
        super(ExceptionWithDetails, self).__init__()
        self.results = None  # type: Optional[Any]


class MetadataError(ExceptionWithDetails):
    def __init__(self, name, version, ex):
        super(MetadataError, self).__init__()
        self.name = name
        self.version = version
        self.ex = ex

    def __str__(self):
        return "Failed to parse metadata for package {} ({}) - {}: {}".format(
            self.name, self.version, self.ex.__class__.__name__, str(self.ex)
        )


class NoCandidateException(ExceptionWithDetails):
    def __init__(self, req, results=None):
        super(NoCandidateException, self).__init__()
        self.req = req
        self.results = results
        self.check_level = 0

    def __str__(self):
        if self.req.specifier:
            return 'NoCandidateException - no candidate for "{}" satisfies {}'.format(
                self.req.name, self.req.specifier
            )
        return 'NoCandidateException - no candidates found for "{}"'.format(
            self.req.name
        )
