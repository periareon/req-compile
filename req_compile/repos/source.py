"""Definition of source repository"""
from __future__ import print_function

import collections
import functools
import itertools
import os
from multiprocessing.pool import ThreadPool
from typing import Deque, Dict, Iterable, List, Optional, Tuple, Callable

import six
from six.moves import map

import req_compile.errors
import req_compile.metadata
import req_compile.metadata.metadata
import req_compile.repos.repository
from req_compile import utils
from req_compile.containers import RequirementContainer
from req_compile.repos.repository import Repository
from req_compile.utils import parse_version

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
    def __init__(self, path, excluded_paths=None, marker_files=None, parallelism=1):
        # type: (str, Iterable[str], Iterable[str], int) -> None
        """
        A repository for Python projects source code on the filesystem. Directories containing a setup.py
        or PEP517 pyproject.toml are included in the list of potential distributions

        Args:
            path (str): Base directory of the source tree
            excluded_paths (list[str]): List of paths to exclude from the source tree. All others, except for
                those included in `SPECIAL_DIRS`
            marker_files (list[str]): Files or directories, that if present, indicate that a discovered
                source directory should not be included in the repository
            parallelism: Number of in-process threads to execute when discovering source projects
        """
        super(SourceRepository, self).__init__("source", allow_prerelease=True)

        if not os.path.exists(path):
            raise ValueError(
                "Source directory {} does not exist (cwd={})".format(path, os.getcwd())
            )

        self.path = os.path.abspath(path)
        self.distributions = collections.defaultdict(
            list
        )  # type: Dict[str, List[req_compile.repos.repository.Candidate]]
        self.marker_files = set(MARKER_FILES)
        self.parallelism = parallelism

        if marker_files:
            self.marker_files |= set(marker_files)

        self._find_later = collections.deque()  # type: Deque[str]
        self._find_all_distributions(
            [os.path.abspath(path) for path in (excluded_paths or [])]
        )

    def _extract_metadata(self, allow_setup_py, source_dir):
        # type: (bool, str) -> Tuple[str, Optional[RequirementContainer]]
        if not allow_setup_py:
            if os.path.exists(os.path.join(source_dir, "setup.py")):
                self._find_later.append(source_dir)
                return source_dir, None

        try:
            self.logger.debug("Processing %s", source_dir)
            return (
                source_dir,
                req_compile.metadata.extract_metadata(source_dir, origin=self),
            )
        except req_compile.errors.MetadataError as ex:
            self.logger.error(
                "Failed to parse metadata for %s - %s", source_dir, str(ex)
            )
            return source_dir, None

    def _find_all_distributions(self, excluded_paths):
        # type: (Iterable[str]) -> None
        """Find all source distribution possible locations"""
        source_dirs = set(self._find_all_source_dirs(excluded_paths))

        # Loading source distributions via threads can be significantly faster because
        # it is a lot of I/O
        if self.parallelism == 1:
            pool = None  # type: Optional[ThreadPool]
            map_func = six.moves.map  # type: Callable
        else:
            pool = ThreadPool(self.parallelism)
            map_func = pool.imap_unordered
        try:
            for source_dir, result in map_func(
                functools.partial(self._extract_metadata, False), source_dirs
            ):
                if result is not None:
                    self._add_distribution(source_dir, result)
        finally:
            if pool is not None:
                pool.close()

        if self._find_later:
            for source_dir, result in map(
                functools.partial(self._extract_metadata, True), self._find_later
            ):
                if result is not None:
                    self._add_distribution(source_dir, result)

    def _add_distribution(self, source_dir, result):
        # type: (str, RequirementContainer) -> None
        if result.version is None:
            self.logger.debug("Source dir %s did not provide a version")
            result.version = parse_version("0")
        candidate = req_compile.repos.repository.Candidate(
            result.name,
            source_dir,
            result.version,
            None,
            None,
            "any",
            None,
            req_compile.repos.repository.DistributionType.SOURCE,
        )
        candidate.preparsed = result
        self.distributions[utils.normalize_project_name(result.name)].append(candidate)

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

            if root != self.path and has_marker:
                dirs[:] = []
                continue

            root_is_valid = False
            for filename in files:
                if root != self.path and filename in self.marker_files:
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
