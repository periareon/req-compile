from __future__ import annotations

import abc
import enum
import logging
import os
import re
from typing import (
    Any,
    Dict,
    Iterable,
    Iterator,
    Optional,
    Sequence,
    Set,
    Tuple,
    Type,
    Union,
)

import packaging.requirements
import packaging.version

import req_compile.errors
import req_compile.utils
from req_compile.containers import RequirementContainer
from req_compile.errors import NoCandidateException
from req_compile.filename import parse_source_filename
from req_compile.target import (  # pylint: disable=unused-import
    INTERPRETER_TAGS,
    LEGACY_ALIASES,
    MACOSX_REGEX,
    MANYLINUX_REGEX,
    TargetEnvironment,
    resolve,
)
from req_compile.utils import NormName, normalize_project_name, parse_version


def manylinux_tag_is_compatible_with_this_system(tag: str) -> bool:
    """Whether a manylinux platform tag can be installed on the host."""
    return resolve(None).manylinux_tag_is_compatible(tag)


class RepositoryInitializationError(ValueError):
    """Failure to initialize a repository"""

    def __init__(self, repo_type: Type[Repository], message: str) -> None:
        super(RepositoryInitializationError, self).__init__(message)
        self.type = repo_type


class DistributionType(enum.IntEnum):
    SOURCE = 2
    WHEEL = 1
    SDIST = 0


class PythonVersionRequirement:
    def check_compatibility(self, target: Optional[TargetEnvironment] = None) -> bool:
        raise NotImplementedError


def _impl_major_minor(py_version: str) -> Tuple[str, int, int]:
    """Split a python version tag into the implementation and a major and
    minor version. If the minor version is not reported, return zero. If any
    parts are invalid, choose results that should sort them last"""
    impl = py_version[:2]
    major = 0
    minor = 0
    try:
        if not impl[0].isalpha() or not impl[1].isalpha():
            impl = "xx"
        major = int(py_version[2])
        minor = int(py_version[3:])
    except (ValueError, IndexError):
        pass
    return impl, major, minor


def _is_py_version_compatible(py_version: str, target: TargetEnvironment) -> bool:
    impl, major, minor = _impl_major_minor(py_version)
    if impl == "py" or impl == target.interpreter:
        if major == target.python_version[0] and minor <= target.python_version[1]:
            return True
    return False


def _py_version_score(py_version: str) -> int:
    # Integer will look like:
    # 0xMNAABB where
    # A is the first digit of the implementation code (e.g. cp for Cython)
    # B is the second digit
    # M is the implementation major version
    # N is the implementation minor version (0 if omitted)

    # Bias CPython higher, and naked py always at the bottom
    impl_score_defaults = {
        "cp": 0xFFFF,
        "py": 0x0000,
    }

    impl, major, minor = _impl_major_minor(py_version)
    impl_score = impl_score_defaults.get(impl)

    if impl_score is None:
        impl_score = ord(impl[0]) << 8 | ord(impl[1])

    score = impl_score | (major << 20) | (minor << 16)
    return score


class WheelVersionTags(PythonVersionRequirement):
    def __init__(self, py_versions: Iterable[str]) -> None:
        assert not isinstance(py_versions, str)
        self.py_versions: Optional[Set[str]] = None
        if py_versions is not None:
            self.py_versions = set(py_versions)

    def check_compatibility(self, target: Optional[TargetEnvironment] = None) -> bool:
        """Whether any of the python tags can be installed on the target."""
        if not self.py_versions:
            return True

        target = resolve(target)
        return any(
            _is_py_version_compatible(py_version, target)
            for py_version in self.py_versions
        )

    def __str__(self) -> str:
        if not self.py_versions:
            return "any"

        return ".".join(sorted(self.py_versions))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, WheelVersionTags):
            return False
        return self.py_versions == other.py_versions

    @property
    def tag_score(self) -> int:
        """Calculate a score based on how specific the versions given are"""
        if not self.py_versions:
            return 0
        return max(_py_version_score(py_version) for py_version in self.py_versions)


class Candidate:  # pylint: disable=too-many-instance-attributes
    """A candidate representing come kind of distribution to resolve"""

    def __init__(
        self,
        name: str,
        filename: Optional[str],
        version: packaging.version.Version,
        py_version: Optional[WheelVersionTags],
        abi: Optional[str],
        plats: Union[str, Iterable[str]],
        link: Any,
        candidate_type: DistributionType = DistributionType.SDIST,
        extra_sort_info: Any = "",
    ) -> None:
        """
        Args:
            name: Name of the candidate
            filename: The filename of the source of the candidate
            version: Version of the candidate
            py_version (RequiresPython): Python version
            abi: The ABI implemented
            plats: Platforms supported by this candidate
            link: URL from which to obtain the wheel
            candidate_type: The nature of the candidate, describing the distribution
        """
        self.name = name
        self.filename = filename
        self.version: packaging.version.Version = version or parse_version("0.0.0")
        self.py_version = py_version
        self.abi = abi
        if isinstance(plats, str):
            self.platforms = {plats}
        else:
            self.platforms = set(plats)
        self.link = link
        self.type = candidate_type

        # Sort based on tags to make sure the most specific distributions
        # are matched first. The score depends on the target, so cache per target.
        self._sort_keys: Dict[
            TargetEnvironment,
            Tuple[packaging.version.Version, Any, int, Tuple[int, int, int, int]],
        ] = {}
        self.extra_sort_info = extra_sort_info

        self.preparsed: Optional[RequirementContainer] = None

        # Repository this candidate came from.
        self.source: Optional[Repository] = None

    @property
    def sortkey(
        self,
    ) -> Tuple[packaging.version.Version, Any, int, Tuple[int, int, int, int]]:
        """The sort key for the host. Prefer `sort_key` with an explicit target."""
        return self.sort_key(None)

    def sort_key(
        self, target: Optional[TargetEnvironment]
    ) -> Tuple[packaging.version.Version, Any, int, Tuple[int, int, int, int]]:
        """Key ranking this candidate for the given target. Higher sorts first."""
        target = resolve(target)
        key = self._sort_keys.get(target)
        if key is None:
            key = (
                self.version,
                self.extra_sort_info,
                self.type.value,
                self.tag_score(target),
            )
            self._sort_keys[target] = key
        return key

    def tag_score(
        self, target: Optional[TargetEnvironment] = None
    ) -> Tuple[int, int, int, int]:
        """Score the wheel tags of this candidate for the given target."""
        target = resolve(target)
        py_version_score = (
            self.py_version.tag_score if self.py_version is not None else 0
        )
        try:
            abi_score = target.abi_tags.index(self.abi) if self.abi is not None else 0
        except ValueError:
            abi_score = 0

        plat_score = -1
        for plat in self.platforms:
            if plat == "any":
                plat_score = 0
                continue
            try:
                plat = LEGACY_ALIASES.get(plat, plat)
                manylinux_match = re.match(MANYLINUX_REGEX, plat)
                if manylinux_match is not None:
                    this_score = int(manylinux_match.groups()[0]) * 10 + int(
                        manylinux_match.groups()[1]
                    )
                else:
                    this_score = len(target.platform_tags) - target.platform_tags.index(
                        plat.lower()
                    )
                plat_score = max(plat_score, this_score * 100)
            except ValueError:
                pass

        # Give a bonus to wheels that support more platforms
        if plat_score > 0:
            plat_score += len(self.platforms)

        # Spaces in source dist filenames penalize them in the search order
        extra_score = (
            0 if isinstance(self.filename, str) and " " in self.filename else 1
        )
        return py_version_score, plat_score, abi_score, extra_score

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Candidate)
            and self.name == other.name
            and self.filename == other.filename
            and self.version == other.version
            and self.py_version == other.py_version
            and self.abi == other.abi
            and self.platforms == other.platforms
            and self.link == other.link
            and self.type == other.type
        )

    def __repr__(self) -> str:
        return (
            "Candidate(name={}, filename={}, version={}, py_versions={}, "
            "abi={}, platform={}, link={})".format(
                self.name,
                self.filename,
                self.version,
                self.py_version,
                self.abi,
                self.platforms,
                self.link,
            )
        )

    def __str__(self) -> str:
        return "{} {}-{}-{}-{}-{}".format(
            self.type.name,
            self.name,
            self.version,
            self.py_version if self.py_version else "none",
            self.abi if self.abi is not None else "none",
            ".".join(sorted(self.platforms)),
        ).strip("\r\n")


def filename_to_candidate(source: Any, filename: str) -> Optional[Candidate]:
    """Create a candidate from a given filename. The source is used to download the
    candidate if necessary.

    Args:

    """
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext == ".egg":
        return None

    if ext == ".whl":
        return _wheel_filename_to_candidate(source, filename)

    if ext in (".gz", ".tgz", ".zip", ".tar", ".bz2"):
        # Best effort skip of dumb binary distributions
        if ".linux-" in filename or ".win-" in filename or ".macosx-" in filename:
            return None
        return _tar_gz_filename_to_candidate(source, filename)
    return None


def _wheel_filename_to_candidate(source: Any, filename: str) -> Optional[Candidate]:
    """Produce a candidate from a wheel filename.

    Args:
        source: Source of the wheel, like a webpage link or a findlinks path.
        filename: Filename to parse to produce the candidate.

    Returns:
        The candidate from the wheel name if possible, providing name, version,
        compatibility information to use when selecting which distributions to actually
        download.
    """
    filename = os.path.basename(filename)
    data_parts = filename[:-4].split("-")
    if len(data_parts) < 5:
        logging.getLogger("req_compile.repository").debug(
            "Unable to use %s, improper filename", filename
        )
        return None

    has_build_tag = len(data_parts) == 6
    build_tag = ""
    if has_build_tag:
        build_tag = data_parts.pop(2)
    name = data_parts[0]
    abi = data_parts[3]
    try:
        #  Convert old-style post-versions to new style so it will sort correctly
        version = parse_version(data_parts[1].replace("_", "-"))
    except Exception:  # pylint: disable=broad-except
        return None
    plats = data_parts[4].split(".")
    requires_python = WheelVersionTags(tuple(data_parts[2].split(".")))

    return Candidate(
        name,
        filename,
        version,
        requires_python,
        abi if abi != "none" else None,
        plats,
        source,
        candidate_type=DistributionType.WHEEL,
        extra_sort_info=build_tag,
    )


def _tar_gz_filename_to_candidate(source: Tuple[str, str], filename: str) -> Candidate:
    """Create a candidate from a source distribution filename.

    Args:
        source: The original link or filename that this source dist came from.
        filename: The filename to parse to produce a candidate.

    Returns:
        The candidate providing name, version, compatibility information to use when
            selecting which distributions to actually download.
    """
    name, version = parse_source_filename(os.path.basename(filename))
    if version is None:
        version = parse_version("0.0+missing")
    return Candidate(
        name,
        os.path.basename(filename),
        version,
        py_version=None,  # Can't tell Python versions supported by filename
        abi=None,
        plats="any",
        link=source,
        candidate_type=DistributionType.SDIST,
    )


def _check_platform_compatibility(
    py_platforms: Iterable[str], target: TargetEnvironment
) -> bool:
    return any(target.platform_tag_is_compatible(plat) for plat in py_platforms)


def _check_abi_compatibility(abi: str, target: TargetEnvironment) -> bool:
    return target.abi_tag_is_compatible(abi)


class CantUseReason(enum.Enum):
    U_CAN_USE = 0
    WRONG_PYTHON_VERSION = 2
    WRONG_PLATFORM = 3
    IS_PRERELEASE = 4
    VERSION_NO_SATISFY = 5
    BAD_METADATA = 6
    NAME_DOESNT_MATCH = 7
    WRONG_ABI = 8
    SOURCE_DIST_NOT_ALLOWED = 9


def sort_candidates(
    candidates: Iterable[Candidate], target: Optional[TargetEnvironment] = None
) -> Sequence[Candidate]:
    """Sort candidates for highest compatibility and version

    Args:
        candidates: Candidates to sort
        target: The environment being compiled for. Defaults to the host.

    Returns:
        The sorted list, starting with the best matching candidate
    """
    target = resolve(target)
    return sorted(candidates, key=lambda x: x.sort_key(target), reverse=True)


def check_usability(
    req: Optional[packaging.requirements.Requirement],
    candidate: Candidate,
    has_equality: bool = False,
    allow_prereleases: bool = False,
    target: Optional[TargetEnvironment] = None,
) -> Optional[CantUseReason]:
    """Determine whether a candidate can be used for the requirement on the target.

    Returns:
        The reason the candidate cannot be used, or None if it can.
    """
    target = resolve(target)
    if (
        candidate.py_version is not None
        and not candidate.py_version.check_compatibility(target)
    ):
        return CantUseReason.WRONG_PYTHON_VERSION

    if candidate.abi is not None and not _check_abi_compatibility(
        candidate.abi, target
    ):
        return CantUseReason.WRONG_ABI

    if not _check_platform_compatibility(candidate.platforms, target):
        return CantUseReason.WRONG_PLATFORM

    if not has_equality and not allow_prereleases and candidate.version.is_prerelease:
        return CantUseReason.IS_PRERELEASE

    if req is not None and not req.specifier.contains(
        candidate.version, prereleases=has_equality or allow_prereleases
    ):
        return CantUseReason.VERSION_NO_SATISFY

    return None


def filter_candidates(
    req: Optional[packaging.requirements.Requirement],
    candidates: Iterable[Candidate],
    allow_prereleases: bool = False,
    target: Optional[TargetEnvironment] = None,
) -> Iterable[Candidate]:
    """Filter candidates down to the ones usable for the requirement on the target."""
    has_equality = (
        req_compile.utils.is_pinned_requirement(req) if req is not None else False
    )
    target = resolve(target)

    return [
        candidate
        for candidate in candidates
        if check_usability(
            req,
            candidate,
            has_equality=has_equality,
            allow_prereleases=allow_prereleases,
            target=target,
        )
        is None
    ]


def _is_all_prereleases(candidates: Iterable[Candidate]) -> bool:
    all_prereleases = True
    for candidate in candidates:
        all_prereleases = all_prereleases and candidate.version.is_prerelease
    return all_prereleases


class Repository(metaclass=abc.ABCMeta):
    def __init__(
        self,
        logger_name: str,
        allow_prerelease: Optional[bool] = None,
        target: Optional[TargetEnvironment] = None,
    ) -> None:
        """
        Args:
            logger_name: Name of the child logger for this repository.
            allow_prerelease: Whether prereleases may be selected.
            target: The environment distributions are selected for. Defaults to the host.
        """
        super(Repository, self).__init__()
        if allow_prerelease is None:
            allow_prerelease = False
        self.logger = logging.getLogger("req_compile.repository").getChild(logger_name)
        self.allow_prerelease = allow_prerelease
        self.target = resolve(target)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Repository):
            return False
        return self.allow_prerelease == other.allow_prerelease

    def __iter__(self) -> Iterator[Repository]:
        return iter([self])

    @abc.abstractmethod
    def get_candidates(
        self, req: Optional[packaging.requirements.Requirement]
    ) -> Iterable[Candidate]:
        """
        Fetch all available candidates for a given requirement.

        Args:
            req (Requirement): Requirement to get candidates for. If None, return all
                candidates for any requirement in the repository.

        Returns:
            List of candidates, provided in the order of best matching the given requirement.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def resolve_candidate(
        self, candidate: Candidate
    ) -> Tuple[RequirementContainer, bool]:
        """Resolve a candidate into actual usable requirements."""
        raise NotImplementedError

    def close(self) -> None:
        """Clean up any open files or connections."""

    def get_dist(
        self,
        req: packaging.requirements.Requirement,
        allow_source_dist: bool = True,
        max_downgrade: Optional[int] = None,
    ) -> Tuple[RequirementContainer, bool]:
        """Fetch the best matching distribution for the given requirement.

        Args:
            req: Requirement to find a match for
            allow_source_dist: Whether to allow a source distribution for this project.
            max_downgrade: Maximum number of different versions to try if
                metadata parsing fails.

        Returns:
            Tuple of the best matching candidate and whether the result came from a cache
        """
        self.logger.info("Getting candidate for %s", req)
        candidates = self.get_candidates(req)
        return self.do_get_candidate(
            req,
            candidates,
            allow_source_dist=allow_source_dist,
            max_downgrade=max_downgrade,
        )

    def do_get_candidate(
        self,
        req: packaging.requirements.Requirement,
        candidates: Iterable[Candidate],
        allow_source_dist: bool = True,
        force_allow_prerelease: bool = False,
        max_downgrade: Optional[int] = None,
    ) -> Tuple[RequirementContainer, bool]:
        """
        Args:
            req: Requirement to fetch candidate for
            candidates: Available candidates (any versions, unsorted)
            allow_source_dist: Whether to allow a source distribution for this project.
            force_allow_prerelease: Override the allow prerelease setting
            max_downgrade: Number of different versions to try. Does not limit number of candidates
                per version nor make any judgements about the semver

        Raises:
            NoCandidateException if no candidate could be found, or IO errors related to failing
                to fetch the desired candidate

        Returns:
            The distribution and whether or not it was cached
        """
        allow_prereleases = force_allow_prerelease or self.allow_prerelease
        if candidates:
            filtered_candidates = filter_candidates(
                req,
                candidates,
                allow_prereleases=allow_prereleases,
                target=self.target,
            )
            tried_versions = set()

            for candidate in sort_candidates(filtered_candidates, target=self.target):
                if candidate.version is None:
                    self.logger.warning(
                        "Found candidate with no version: %s", candidate
                    )
                    continue

                if candidate.type == DistributionType.SDIST:
                    if allow_source_dist:
                        self.logger.warning(
                            "Considering source distribution for %s", candidate.name
                        )
                        if not self.target.is_host:
                            self.logger.warning(
                                "Metadata for the source distribution %s is extracted "
                                "on this machine and may not match the target %s",
                                candidate,
                                self.target,
                            )
                    else:
                        self.logger.debug(
                            "Skipping source distribution %s for %s (due to --only-binary)",
                            candidate,
                            candidate.name,
                        )
                        continue

                try:
                    dist, cached = self.resolve_candidate(candidate)
                    if dist is not None:
                        if normalize_project_name(
                            candidate.name
                        ) == normalize_project_name(req.name):
                            dist.candidate = candidate
                            return dist, cached
                except req_compile.errors.MetadataError as ex:
                    self.logger.warning(
                        "Could not use candidate %s - %s", candidate, ex
                    )

                tried_versions.add(candidate.version)
                if max_downgrade is not None and len(tried_versions) >= max_downgrade:
                    break

        if (
            _is_all_prereleases(candidates) or req_compile.utils.has_prerelease(req)
        ) and not allow_prereleases:
            self.logger.debug(
                "No non-prerelease candidates available. Now allowing prereleases"
            )
            return self.do_get_candidate(
                req,
                candidates,
                force_allow_prerelease=True,
                allow_source_dist=allow_source_dist,
                max_downgrade=max_downgrade,
            )

        raise NoCandidateException(req)

    # pylint: disable-next=invalid-name
    def why_cant_I_use(
        self,
        req: packaging.requirements.Requirement,
        candidate: Candidate,
        only_binary: Optional[Set[NormName]] = None,
    ) -> CantUseReason:
        reason = check_usability(
            req,
            candidate,
            allow_prereleases=self.allow_prerelease,
            target=self.target,
        )
        if reason is None or reason == CantUseReason.U_CAN_USE:
            if (
                candidate.type == DistributionType.SDIST
                and only_binary is not None
                and candidate.name in only_binary
            ):
                return CantUseReason.SOURCE_DIST_NOT_ALLOWED

            try:
                self.resolve_candidate(candidate)
            except req_compile.errors.MetadataError:
                return CantUseReason.BAD_METADATA
            return CantUseReason.U_CAN_USE

        return reason


BaseRepository = Repository
