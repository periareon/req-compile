from __future__ import print_function

import enum
import logging
import os
import platform
import re
import sys
import sysconfig
from typing import Iterable, Optional, Sequence, Tuple, Any, Union, Set
import distutils.util  # pylint: disable=import-error,no-name-in-module,no-member

import packaging.version
import pkg_resources
import six

import req_compile.errors
import req_compile.utils
from req_compile.containers import RequirementContainer
from req_compile.errors import NoCandidateException
from req_compile.filename import parse_source_filename
from req_compile.utils import get_glibc_version, normalize_project_name, parse_version

INTERPRETER_TAGS = {
    "CPython": "cp",
    "IronPython": "ip",
    "PyPy": "pp",
    "Jython": "jy",
}

INTERPRETER_TAG = INTERPRETER_TAGS.get(platform.python_implementation(), "cp")
PY_VERSION_NUM = str(sys.version_info.major) + str(sys.version_info.minor)

# PEP-600 legacy platform tags
LEGACY_ALIASES = {
    "manylinux1_x86_64": "manylinux_2_5_x86_64",
    "manylinux1_i686": "manylinux_2_5_i686",
    "manylinux2010_x86_64": "manylinux_2_12_x86_64",
    "manylinux2010_i686": "manylinux_2_12_i686",
    "manylinux2014_x86_64": "manylinux_2_17_x86_64",
    "manylinux2014_i686": "manylinux_2_17_i686",
}
MANYLINUX_REGEX = r"manylinux_([0-9]+)_([0-9]+)_(.*)"


def _get_platform_tags():
    # type: () -> Sequence[str]
    if sys.platform == "darwin":
        version, _, arch = platform.mac_ver()
        major, minor_str = version.split(".")[:2]
        mac_tags = []
        minor = int(minor_str)
        while minor >= 6:
            mac_tags.append(
                "macosx_{major}_{minor}_{arch}".format(
                    major=major, minor=minor, arch=arch
                )
            )
            mac_tags.append(
                "macosx_{major}_{minor}_intel".format(major=major, minor=minor)
            )
            minor -= 1
        return mac_tags

    plat = distutils.util.get_platform()  # pylint: disable=no-member
    return (plat.replace(".", "_").replace("-", "_"),)


def get_system_arch():
    uname_info = platform.uname()
    return uname_info[4]


def manylinux_tag_is_compatible_with_this_system(tag):
    # Pulled from PEP 600
    # Normalize and parse the tag
    glibc_version = get_glibc_version()
    if glibc_version is None:
        return False

    tag = LEGACY_ALIASES.get(tag, tag)
    manylinux_match = re.match(MANYLINUX_REGEX, tag)
    if not manylinux_match:
        return False
    tag_major_str, tag_minor_str, tag_arch = manylinux_match.groups()
    tag_major = int(tag_major_str)
    tag_minor = int(tag_minor_str)

    sys_major, sys_minor = glibc_version
    if (sys_major, sys_minor) < (tag_major, tag_minor):
        return False
    sys_arch = get_system_arch()
    if sys_arch != tag_arch:
        return False

    # Check for manual override
    try:
        import _manylinux  # type: ignore  # pylint: disable=bad-option-value,import-outside-toplevel
    except ImportError:
        pass
    else:
        if hasattr(_manylinux, "manylinux_compatible"):
            result = _manylinux.manylinux_compatible(
                tag_major,
                tag_minor,
                tag_arch,
            )
            if result is not None:
                return bool(result)
        else:
            if (tag_major, tag_minor) == (2, 5):
                if hasattr(_manylinux, "manylinux1_compatible"):
                    return bool(_manylinux.manylinux1_compatible)
            if (tag_major, tag_minor) == (2, 12):
                if hasattr(_manylinux, "manylinux2010_compatible"):
                    return bool(_manylinux.manylinux2010_compatible)

    return True


def _get_abi_tag():
    # type: () -> str
    """Build a best effort ABI tag"""
    py_version = (sys.version_info.major, sys.version_info.minor)
    tag = INTERPRETER_TAG + PY_VERSION_NUM
    if py_version < (3, 8):
        pymalloc = sysconfig.get_config_var("WITH_PYMALLOC")
        if pymalloc or pymalloc is None:
            tag += "m"
        if py_version < (3, 3):
            unicode_size = sysconfig.get_config_var("Py_UNICODE_SIZE")
            if unicode_size == 4 or (
                unicode_size is None and sys.maxunicode == 0x10FFFF
            ):
                tag += "u"
    return tag


PLATFORM_TAGS = _get_platform_tags()
ABI_TAGS = ("abi" + str(sys.version_info.major), _get_abi_tag())


class RepositoryInitializationError(ValueError):
    """Failure to initialize a repository"""

    def __init__(self, repo_type, message):
        super(RepositoryInitializationError, self).__init__(message)
        self.type = repo_type


class DistributionType(enum.IntEnum):
    SOURCE = 2
    WHEEL = 1
    SDIST = 0


class PythonVersionRequirement(object):
    def check_compatibility(self):
        raise NotImplementedError


def _impl_major_minor(py_version):
    # type: (str) -> Tuple[str, int, int]
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


def _is_py_version_compatible(py_version):
    # type: (str) -> bool
    impl, major, minor = _impl_major_minor(py_version)
    if impl == "py" or impl == INTERPRETER_TAG:
        if major == sys.version_info.major and minor <= sys.version_info.minor:
            return True
    return False


def _py_version_score(py_version):
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
    def __init__(self, py_versions):
        # type: (Iterable[str]) -> None
        assert not isinstance(py_versions, str)
        if py_versions is None:
            self.py_versions = None  # type: Optional[Set[str]]
        else:
            self.py_versions = set(py_versions)

    def check_compatibility(self):
        # type: () -> bool
        if not self.py_versions:
            return True

        return any(
            _is_py_version_compatible(py_version) for py_version in self.py_versions
        )

    def __str__(self):
        # type: () -> str
        if not self.py_versions:
            return "any"

        return ".".join(sorted(self.py_versions))

    def __eq__(self, other):
        return self.py_versions == other.py_versions

    @property
    def tag_score(self):
        # type: () -> int
        """Calculate a score based on how specific the versions given are"""
        if not self.py_versions:
            return 0
        return max(_py_version_score(py_version) for py_version in self.py_versions)


class Candidate(object):  # pylint: disable=too-many-instance-attributes
    """A candidate representing come kind of distribution to resolve"""

    def __init__(
        self,
        name,  # type: str
        filename,  # type: Optional[str]
        version,  # type: packaging.version.Version
        py_version,  # type: Optional[WheelVersionTags]
        abi,  # type: Optional[str]
        plats,  # type: Union[str, Iterable[str]]
        link,  # type: Optional[str]
        candidate_type=DistributionType.SDIST,  # type: DistributionType
        extra_sort_info="",  # type: str
    ):
        # type: (...) -> None
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
        self.version = version or parse_version(
            "0.0.0"
        )  # type: packaging.version.Version
        self.py_version = py_version
        self.abi = abi
        if isinstance(plats, six.string_types):
            self.platforms = {plats}
        else:
            self.platforms = set(plats)
        self.link = link
        self.type = candidate_type

        # Sort based on tags to make sure the most specific distributions
        # are matched first
        self._sortkey = (
            None
        )  # type: Optional[Tuple[packaging.version.Version, str, int, Tuple[int, int, int, int]]]
        self._extra_sort_info = extra_sort_info

        self.preparsed = None  # type: Optional[RequirementContainer]

    @property
    def sortkey(self):
        # type: () -> Tuple[packaging.version.Version, str, int, Tuple[int, int, int, int]]
        if self._sortkey is None:
            self._sortkey = (
                self.version,
                self._extra_sort_info,
                self.type.value,
                self.tag_score,
            )
        return self._sortkey

    @property
    def tag_score(self):
        # type: () -> Tuple[int, int, int, int]
        py_version_score = (
            self.py_version.tag_score if self.py_version is not None else 0
        )
        try:
            abi_score = ABI_TAGS.index(self.abi) if self.abi is not None else 0
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
                    this_score = len(PLATFORM_TAGS) - PLATFORM_TAGS.index(plat.lower())
                plat_score = max(plat_score, this_score * 100)
            except ValueError:
                pass

        # Give a bonus to wheels that support more platforms
        if plat_score > 0:
            plat_score += len(self.platforms)

        # Spaces in source dist filenames penalize them in the search order
        extra_score = (
            0
            if isinstance(self.filename, six.string_types) and " " in self.filename
            else 1
        )
        return py_version_score, plat_score, abi_score, extra_score

    def __eq__(self, other):
        # type: (Any) -> bool
        return (
            self.name == other.name
            and self.filename == other.filename
            and self.version == other.version
            and self.py_version == other.py_version
            and self.abi == other.abi
            and self.platforms == other.platforms
            and self.link == other.link
            and self.type == other.type
        )

    def __repr__(self):
        # type: () -> str
        return "Candidate(name={}, filename={}, version={}, py_versions={}, abi={}, platform={}, link={})".format(
            self.name,
            self.filename,
            self.version,
            self.py_version,
            self.abi,
            self.platforms,
            self.link,
        )

    def __str__(self):
        # type: () -> str
        py_version_str = str(self.py_version) + "-"
        return "{} {}-{}-{}{}-{}".format(
            self.type.name,
            self.name,
            self.version,
            py_version_str,
            self.abi,
            ".".join(sorted(self.platforms)),
        )


def process_distribution(source, filename):
    # type: (str, str) -> Optional[Candidate]
    candidate = None
    if filename.endswith(".egg"):
        return None
    if ".whl" in filename:
        candidate = _wheel_candidate(source, filename)
    elif (
        ".tar.gz" in filename
        or ".tgz" in filename
        or ".zip" in filename
        or ".tar.bz2" in filename
    ):
        # Best effort skip of dumb binary distributions
        if ".linux-" in filename or ".win-" in filename or ".macosx-" in filename:
            return None
        candidate = _tar_gz_candidate(source, filename)
    return candidate


def _wheel_candidate(source, filename):
    # type: (str, str) -> Optional[Candidate]
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
    #  Convert old-style post-versions to new style so it will sort correctly
    version = parse_version(data_parts[1].replace("_", "-"))
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


def _tar_gz_candidate(source, filename):
    # type: (str, str) -> Candidate
    name, version = parse_source_filename(os.path.basename(filename))
    return Candidate(
        name,
        filename,
        version,
        None,
        None,
        "any",
        source,
        candidate_type=DistributionType.SDIST,
    )


def _check_platform_compatibility(py_platforms):
    # type: (Iterable[str]) -> bool
    return (
        "any" in py_platforms
        or any(py_platform.lower() in PLATFORM_TAGS for py_platform in py_platforms)
        or any(
            manylinux_tag_is_compatible_with_this_system(py_platform)
            for py_platform in py_platforms
        )
    )


def _check_abi_compatibility(abi):
    # type: (str) -> bool
    return abi in ABI_TAGS


class BaseRepository(object):
    def get_candidate(self, req, max_downgrade=None):
        # type: (pkg_resources.Requirement, int) -> Tuple[RequirementContainer, bool]
        """Fetch the best matching candidate for the given requirement

        Args:
            req: Requirement to find a match for
            max_downgrade: Maximum number of different versions to try if
                metadata parsing fails

        Returns:
            Tuple of the best matching candidate and whether or not the result came from a cache
        """
        raise NotImplementedError()


class CantUseReason(enum.Enum):
    U_CAN_USE = 0
    WRONG_PYTHON_VERSION = 2
    WRONG_PLATFORM = 3
    IS_PRERELEASE = 4
    VERSION_NO_SATISFY = 5
    BAD_METADATA = 6
    NAME_DOESNT_MATCH = 7
    WRONG_ABI = 8


def sort_candidates(candidates):
    # type: (Iterable[Candidate]) -> Sequence[Candidate]
    """Sort candidates for highest compatibility and version

    Args:
        candidates: Candidates to sort

    Returns:
        The sorted list, starting with the best matching candidate
    """
    return sorted(candidates, key=lambda x: x.sortkey, reverse=True)


def check_usability(req, candidate, has_equality=None, allow_prereleases=False):
    # type: (pkg_resources.Requirement, Candidate, bool, bool) -> Optional[CantUseReason]
    if (
        candidate.py_version is not None
        and not candidate.py_version.check_compatibility()
    ):
        return CantUseReason.WRONG_PYTHON_VERSION

    if candidate.abi is not None and not _check_abi_compatibility(candidate.abi):
        return CantUseReason.WRONG_ABI

    if not _check_platform_compatibility(candidate.platforms):
        return CantUseReason.WRONG_PLATFORM

    if not has_equality and not allow_prereleases and candidate.version.is_prerelease:
        return CantUseReason.IS_PRERELEASE

    if req is not None and not req.specifier.contains(  # type: ignore[attr-defined]
        candidate.version, prereleases=has_equality or allow_prereleases
    ):
        return CantUseReason.VERSION_NO_SATISFY

    return None


def filter_candidates(req, candidates, allow_prereleases=False):
    # type: (pkg_resources.Requirement, Iterable[Candidate], bool) -> Iterable[Candidate]
    has_equality = (
        req_compile.utils.is_pinned_requirement(req) if req is not None else False
    )

    for candidate in candidates:
        usability = check_usability(
            req,
            candidate,
            has_equality=has_equality,
            allow_prereleases=allow_prereleases,
        )
        if usability is None:
            yield candidate


def _is_all_prereleases(candidates):
    # type: (Iterable[Candidate]) -> bool
    all_prereleases = True
    for candidate in candidates:
        all_prereleases = all_prereleases and candidate.version.is_prerelease
    return all_prereleases


class Repository(BaseRepository):
    def __init__(self, logger_name, allow_prerelease=None):
        # type: (str, bool) -> None
        super(Repository, self).__init__()
        if allow_prerelease is None:
            allow_prerelease = False
        self.logger = logging.getLogger("req_compile.repository").getChild(logger_name)
        self.allow_prerelease = allow_prerelease

    def __eq__(self, other):
        return self.allow_prerelease == other.allow_prerelease

    def __iter__(self):
        return iter([self])

    def get_candidates(self, req):
        # type: (pkg_resources.Requirement) -> Iterable[Candidate]
        """
        Fetch all available candidates for a project_name
        Args:
            req (Requirement): Requirement to get candidates for

        Returns:
            (list[Candidate]) List of candidates
        """
        raise NotImplementedError()

    def resolve_candidate(self, candidate):
        # type: (Candidate) -> Tuple[Optional[RequirementContainer], bool]
        raise NotImplementedError()

    def close(self):
        # type: () -> None
        raise NotImplementedError()

    def get_candidate(self, req, max_downgrade=None):
        # type: (pkg_resources.Requirement, int) -> Tuple[RequirementContainer, bool]
        self.logger.info("Getting candidate for %s", req)
        candidates = self.get_candidates(req)
        return self.do_get_candidate(req, candidates, max_downgrade=max_downgrade)

    def do_get_candidate(
        self, req, candidates, force_allow_prerelease=False, max_downgrade=None
    ):
        # type: (pkg_resources.Requirement, Iterable[Candidate], bool, int) -> Tuple[RequirementContainer, bool]
        """
        Args:
            req: Requirement to fetch candidate for
            candidates: Available candidates (any versions, unsorted)
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
                req, candidates, allow_prereleases=allow_prereleases
            )
            tried_versions = set()

            for candidate in sort_candidates(filtered_candidates):
                if candidate.version is None:
                    self.logger.warning(
                        "Found candidate with no version: %s", candidate
                    )
                    continue

                if candidate.type == DistributionType.SDIST:
                    self.logger.warning(
                        "Considering source distribution for %s", candidate.name
                    )

                try:
                    dist, cached = self.resolve_candidate(candidate)
                    if dist is not None:
                        if normalize_project_name(
                            candidate.name
                        ) == normalize_project_name(req.project_name):
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
                max_downgrade=max_downgrade,
            )

        raise NoCandidateException(req)

    def why_cant_I_use(self, req, candidate):  # pylint: disable=invalid-name
        # type: (pkg_resources.Requirement, Candidate) -> CantUseReason
        reason = check_usability(
            req,
            candidate,
            allow_prereleases=self.allow_prerelease,
        )
        if reason is None:
            return CantUseReason.U_CAN_USE
        return reason
