"""Definition of source repository"""
from __future__ import print_function
import collections
import itertools
import os

from six.moves import map

import req_compile.metadata.errors
from req_compile import utils
import req_compile.metadata
import req_compile.repos.repository

from req_compile.repos.repository import Repository

# Special directories that will never be considered
SPECIAL_DIRS = {
    "site-packages",
    "dist-packages",
    ".git",
    ".svn",
    ".idea",
    "__pycache__",
    "node_modules",
    "venv",
    ".eggs",
    "build",
    "dist",
}

# Files that if included in a directory would disqualify
# that directory from being included in the repository
MARKER_FILES = {"__init__.py"}


class SourceRepository(Repository):
    def __init__(self, path, excluded_paths=None, marker_files=None):
        """
        A repository for Python projects source code on the filesystem. Directories containing a setup.py
        or PEP517 pyproject.toml are included in the list of potential distributions

        Args:
            path (str): Base directory of the source tree
            excluded_paths (list[str]): List of paths to exclude from the source tree. All others, except for
                those included in `SPECIAL_DIRS`
            marker_files (list[str]): Files or directories, that if present, indicate that a discovered
                source directory should not be included in the repository
        """
        super(SourceRepository, self).__init__("source", allow_prerelease=True)

        if not os.path.exists(path):
            raise ValueError(
                "Source directory {} does not exist (cwd={})".format(path, os.getcwd())
            )

        self.path = os.path.abspath(path)
        self.distributions = collections.defaultdict(list)
        self.marker_files = set(MARKER_FILES)

        if marker_files:
            self.marker_files |= set(marker_files)

        self._find_all_distributions(
            [os.path.abspath(path) for path in (excluded_paths or [])]
        )

    def _extract_metadata(self, source_dir):
        try:
            self.logger.debug("Processing %s (cwd = %s)", source_dir, os.getcwd())
            return (
                source_dir,
                req_compile.metadata.extract_metadata(source_dir, origin=self),
            )
        except req_compile.metadata.errors.MetadataError as ex:
            self.logger.error(
                "Failed to parse metadata for %s - %s", source_dir, str(ex)
            )
            return source_dir, None

    def _find_all_distributions(self, excluded_paths):
        source_dirs = set(self._find_all_source_dirs(excluded_paths))

        results = map(self._extract_metadata, source_dirs)
        for source_dir, result in results:
            if result is not None:
                candidate = req_compile.repos.repository.Candidate(
                    result.name,
                    source_dir,
                    result.version,
                    None,
                    "any",
                    None,
                    req_compile.repos.repository.DistributionType.SOURCE,
                )
                candidate.preparsed = result
                self.distributions[utils.normalize_project_name(result.name)].append(
                    candidate
                )

    def _find_all_source_dirs(self, excluded_paths):
        for root, dirs, files in os.walk(self.path):
            has_marker = False
            for dir_ in list(dirs):
                if (
                    dir_ in SPECIAL_DIRS
                    or dir_.endswith(".egg-info")
                    or dir_.endswith(".dist-info")
                ):
                    dirs.remove(dir_)
                else:
                    for excluded_path in excluded_paths:
                        if os.path.join(root, dir_).startswith(excluded_path):
                            dirs.remove(dir_)
                            break
                if dir_ in self.marker_files:
                    has_marker = True
                    break

            if has_marker:
                continue

            root_is_valid = False
            for filename in files:
                if filename in self.marker_files:
                    dirs[:] = []
                    root_is_valid = False
                    break

                if filename in ("setup.py", "pyproject.toml"):
                    root_is_valid = True

            if root_is_valid:
                # Remove test directories from search
                for dir_ in list(dirs):
                    if (
                        dir_ == "tests"
                        or dir_ == "test"
                        or dir_.endswith("-tests")
                        or dir_.endswith("-test")
                    ):
                        dirs.remove(dir_)
                yield root

    def __repr__(self):
        return "--source {}".format(self.path)

    def __eq__(self, other):
        return (
            isinstance(other, SourceRepository)
            and super(SourceRepository, self).__eq__(other)
            and self.path == other.path
        )

    def __hash__(self):
        return hash("source") ^ hash(self.path)

    def get_candidates(self, req):
        if req is None:
            return itertools.chain(*self.distributions.values())

        project_name = utils.normalize_project_name(req.name)
        return self.distributions.get(project_name, [])

    def resolve_candidate(self, candidate):
        return candidate.preparsed, True

    def close(self):
        pass


class ReferenceSourceRepository(SourceRepository):
    """Represents a source that shows up in solution files but may not itself be present"""

    def __init__(self, dist):
        # Skip the SourceRepository super call
        # pylint: disable=bad-super-call
        super(SourceRepository, self).__init__("ref-source", allow_prerelease=True)
        self.distributions = {dist.name: dist}
