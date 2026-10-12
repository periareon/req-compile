"""Description of the environment a solution is compiled for.

Compilation needs to answer a few platform specific questions: which wheels can
be installed, which ``Requires-Python`` ranges are satisfied, and how PEP 508
environment markers evaluate. All of those answers are derived from a single
:class:`TargetEnvironment`. By default the target is the interpreter running
req-compile, but one can be constructed for any other platform and Python
version, which allows compiling a solution for a machine other than the one
performing the compilation.
"""

from __future__ import annotations

import platform
import re
import sys
import sysconfig
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, cast

import packaging.markers
import packaging.tags
import packaging.version

from req_compile.utils import get_glibc_version

INTERPRETER_TAGS = {
    "CPython": "cp",
    "IronPython": "ip",
    "PyPy": "pp",
    "Jython": "jy",
}

# Marker values keyed by the interpreter tag.
_IMPLEMENTATION_NAMES = {
    "cp": ("cpython", "CPython"),
    "pp": ("pypy", "PyPy"),
    "ip": ("ironpython", "IronPython"),
    "jy": ("jython", "Jython"),
}

MACOSX_REGEX = r"macosx_([0-9]+)_([0-9]+)_(.+)"
MANYLINUX_REGEX = r"manylinux_([0-9]+)_([0-9]+)_(.+)"

# PEP-600 legacy platform tags
LEGACY_ALIASES = {
    "manylinux1_x86_64": "manylinux_2_5_x86_64",
    "manylinux1_i686": "manylinux_2_5_i686",
    "manylinux2010_x86_64": "manylinux_2_12_x86_64",
    "manylinux2010_i686": "manylinux_2_12_i686",
    "manylinux2014_x86_64": "manylinux_2_17_x86_64",
    "manylinux2014_i686": "manylinux_2_17_i686",
    "manylinux2014_aarch64": "manylinux_2_17_aarch64",
    "manylinux2014_armv7l": "manylinux_2_17_armv7l",
    "manylinux2014_ppc64": "manylinux_2_17_ppc64",
    "manylinux2014_ppc64le": "manylinux_2_17_ppc64le",
    "manylinux2014_s390x": "manylinux_2_17_s390x",
}

# Wheel tag to the machine as `platform.uname()` and the `platform_machine`
# marker report it on Windows.
_WINDOWS_PLATFORMS = {
    "win_amd64": "AMD64",
    "win32": "x86",
    "win_arm64": "ARM64",
}


def _mac_platform_tags(
    version: Optional[Tuple[int, int]] = None, arch: Optional[str] = None
) -> Sequence[str]:
    """Produce the ordered macOS platform tags for a macOS release and architecture.

    Earlier entries are ranked higher when sorting candidates.
    """
    mac_platforms = defaultdict(set)

    for plat in packaging.tags.mac_platforms(version, arch):
        match = re.match(MACOSX_REGEX, plat)
        if not match:
            raise ValueError(f"Unexpected MacOS platform: {plat}")

        major, minor, plat_arch = (
            int(match.group(1)),
            int(match.group(2)),
            match.group(3),
        )
        if arch is None:
            # The first tag produced is for the architecture of the host.
            arch = plat_arch
        key = (major, minor)

        # Universal and arm tags are ranked higher.
        mac_platforms[key].add(plat)

        if major == 10 and plat_arch == "universal2":
            mac_platforms[key].add(plat.replace(plat_arch, "x86_64"))
            if int(minor) <= 10:
                mac_platforms[key].add(plat.replace(plat_arch, "intel"))

    def _rank(plat: str) -> Tuple[int, str]:
        # Within a release, prefer wheels built for exactly this architecture,
        # then universal wheels, then anything else.
        plat_arch = plat.split("_", 3)[3]
        if arch is not None and plat_arch == arch:
            return 0, plat
        if plat_arch == "universal2":
            return 1, plat
        return 2, plat

    # Combine all collections of tags where older versions of MacOS
    # are ranked lower than more modern ones
    ordered_mac_plats: List[str] = []
    for ver in reversed(sorted(mac_platforms.keys())):
        ordered_mac_plats.extend(sorted(mac_platforms[ver], key=_rank))

    return ordered_mac_plats


def _host_platform_tags() -> Sequence[str]:
    if sys.platform == "darwin":
        return _mac_platform_tags()

    plat = sysconfig.get_platform()
    return (plat.replace(".", "_").replace("-", "_"),)


def _abi_tags(interpreter: str, python_version: Tuple[int, ...]) -> Tuple[str, ...]:
    """Best effort ABI tags. Later entries are ranked higher when sorting."""
    abi = f"{interpreter}{python_version[0]}{python_version[1]}"
    if interpreter == "cp" and python_version[:2] < (3, 8):
        abi += "m"
    return (f"abi{python_version[0]}", abi)


def _parse_python_version(version: str) -> Tuple[int, int, int]:
    parts = version.strip().split(".")
    if not 2 <= len(parts) <= 3 or not all(part.isdigit() for part in parts):
        raise ValueError(
            f"Invalid Python version {version!r}. Expected a version such as 3.11 or 3.11.4."
        )
    numbers = [int(part) for part in parts]
    while len(numbers) < 3:
        numbers.append(0)
    return numbers[0], numbers[1], numbers[2]


def _host_name(
    platform_tags: Sequence[str], arch: str, glibc: Optional[Tuple[int, int]]
) -> str:
    """The wheel platform tag best describing the machine running req-compile."""
    if sys.platform == "linux" and glibc is not None:
        return f"manylinux_{glibc[0]}_{glibc[1]}_{arch}"
    return platform_tags[0]


class TargetEnvironment:  # pylint: disable=too-many-instance-attributes
    """The platform and interpreter a solution is compiled for.

    Instances are immutable and hashable so they can key caches.
    """

    def __init__(
        self,
        name: str,
        python_version: Tuple[int, int, int],
        python_version_str: str,
        interpreter: str,
        platform_tags: Iterable[str],
        abi_tags: Iterable[str],
        arch: str,
        glibc_version: Optional[Tuple[int, int]],
        marker_environment: Mapping[str, str],
        is_host: bool = False,
    ) -> None:
        """
        Args:
            name: Short description of the platform, e.g. ``linux_x86_64``.
            python_version: The full Python version as a tuple.
            python_version_str: The Python version as it was requested, used for display.
            interpreter: The interpreter tag, e.g. ``cp`` for CPython.
            platform_tags: Wheel platform tags this target can install, best first.
                manylinux tags are not listed, they are checked against ``glibc_version``.
            abi_tags: Wheel ABI tags this target can install, best last.
            arch: The machine architecture as ``uname`` would report it.
            glibc_version: The glibc version of the target, or None if the target
                does not use glibc.
            marker_environment: The complete PEP 508 marker environment.
            is_host: Whether this describes the running interpreter.
        """
        self.name = name
        self.python_version = python_version
        self.python_version_str = python_version_str
        self.interpreter = interpreter
        self.platform_tags: Tuple[str, ...] = tuple(platform_tags)
        self.abi_tags: Tuple[str, ...] = tuple(abi_tags)
        self.arch = arch
        self.glibc_version = glibc_version
        self.marker_environment: Dict[str, str] = dict(marker_environment)
        self.is_host = is_host
        self._key = (
            self.name,
            self.python_version,
            self.interpreter,
            self.platform_tags,
            self.abi_tags,
            self.arch,
            self.glibc_version,
            tuple(sorted(self.marker_environment.items())),
        )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, TargetEnvironment) and self._key == other._key

    def __hash__(self) -> int:
        return hash(self._key)

    def __repr__(self) -> str:
        return (
            f"TargetEnvironment(name={self.name!r}, "
            f"python_version={self.python_version_str!r}, "
            f"interpreter={self.interpreter!r})"
        )

    def __str__(self) -> str:
        return f"{self.name} ({self.interpreter}{self.python_version_str})"

    def replace(self, **changes: Any) -> TargetEnvironment:
        """Create a copy of this target with some attributes replaced."""
        fields: Dict[str, Any] = {
            "name": self.name,
            "python_version": self.python_version,
            "python_version_str": self.python_version_str,
            "interpreter": self.interpreter,
            "platform_tags": self.platform_tags,
            "abi_tags": self.abi_tags,
            "arch": self.arch,
            "glibc_version": self.glibc_version,
            "marker_environment": self.marker_environment,
            "is_host": self.is_host,
        }
        unknown = set(changes) - set(fields)
        if unknown:
            raise TypeError(f"Unknown attributes: {sorted(unknown)}")
        fields.update(changes)
        return TargetEnvironment(**fields)

    @property
    def python_major_minor(self) -> Tuple[int, int]:
        return self.python_version[0], self.python_version[1]

    @property
    def python_full_version(self) -> packaging.version.Version:
        return packaging.version.Version(
            ".".join(str(part) for part in self.python_version)
        )

    def marker_environment_with_extra(self, extra: Optional[str]) -> Dict[str, str]:
        """The marker environment with the ``extra`` marker set."""
        environment = dict(self.marker_environment)
        environment["extra"] = extra or ""
        return environment

    def manylinux_tag_is_compatible(self, tag: str) -> bool:
        """Whether a manylinux wheel platform tag can be installed on this target.

        Implements the compatibility check described in PEP 600.
        """
        if self.glibc_version is None:
            return False

        tag = LEGACY_ALIASES.get(tag, tag)
        manylinux_match = re.match(MANYLINUX_REGEX, tag)
        if not manylinux_match:
            return False
        tag_major_str, tag_minor_str, tag_arch = manylinux_match.groups()
        tag_major = int(tag_major_str)
        tag_minor = int(tag_minor_str)

        if self.glibc_version < (tag_major, tag_minor):
            return False
        if self.arch != tag_arch:
            return False

        if self.is_host:
            override = _manylinux_override(tag_major, tag_minor, tag_arch)
            if override is not None:
                return override
        return True

    def platform_tag_is_compatible(self, tag: str) -> bool:
        """Whether a wheel platform tag can be installed on this target."""
        tag = tag.lower()
        return (
            tag == "any"
            or tag in self.platform_tags
            or self.manylinux_tag_is_compatible(tag)
        )

    def abi_tag_is_compatible(self, abi: str) -> bool:
        """Whether a wheel ABI tag can be installed on this target."""
        if abi in self.abi_tags:
            return True
        if self.interpreter == "pp":
            # PyPy ABI tags carry the PyPy version, e.g. pypy310_pp73, which a
            # target does not know. Accept any PyPy ABI for the right Python version.
            major, minor = self.python_major_minor
            return re.fullmatch(rf"pypy{major}{minor}_pp[0-9]+", abi) is not None
        return False

    @classmethod
    def host(cls) -> TargetEnvironment:
        """Describe the interpreter running req-compile."""
        interpreter = INTERPRETER_TAGS.get(platform.python_implementation(), "cp")
        python_version = (
            sys.version_info.major,
            sys.version_info.minor,
            sys.version_info.micro,
        )
        platform_tags = _host_platform_tags()
        arch = platform.uname()[4]
        glibc_version = get_glibc_version()
        return cls(
            name=_host_name(platform_tags, arch, glibc_version),
            python_version=python_version,
            python_version_str=".".join(str(part) for part in python_version),
            interpreter=interpreter,
            platform_tags=platform_tags,
            abi_tags=_abi_tags(interpreter, python_version),
            arch=arch,
            glibc_version=glibc_version,
            marker_environment=cast(
                Dict[str, str], dict(packaging.markers.default_environment())
            ),
            is_host=True,
        )

    @classmethod
    def from_spec(
        cls,
        platform_spec: Optional[str] = None,
        python_version: Optional[str] = None,
        implementation: Optional[str] = None,
    ) -> TargetEnvironment:
        """Describe a target from command line style arguments.

        Args:
            platform_spec: A wheel platform tag such as ``manylinux_2_28_x86_64``,
                ``macosx_12_0_arm64`` or ``win_amd64``, as accepted by ``pip --platform``.
                Defaults to the host platform.
            python_version: The Python version, e.g. ``3.11`` or ``3.11.4``. Defaults
                to the running interpreter.
            implementation: The interpreter tag, e.g. ``cp``. Defaults to CPython when
                a platform or Python version is given, otherwise the running interpreter.

        Returns:
            The target environment. If no arguments are provided, the host.
        """
        if platform_spec is None and python_version is None and implementation is None:
            return host()

        host_target = host()
        if implementation is None:
            implementation = host_target.interpreter if platform_spec is None else "cp"
        implementation = implementation.lower()
        if not re.fullmatch("[a-z]{2}", implementation):
            raise ValueError(
                f"Invalid implementation {implementation!r}. Expected a two letter "
                "interpreter tag such as cp or pp."
            )

        if python_version is None:
            version = host_target.python_version
            version_str = host_target.python_version_str
        else:
            version = _parse_python_version(python_version)
            version_str = python_version.strip()

        implementation_name, python_implementation = _IMPLEMENTATION_NAMES.get(
            implementation, (implementation, implementation)
        )
        full_version = ".".join(str(part) for part in version)
        marker_environment = {
            "implementation_name": implementation_name,
            "implementation_version": full_version,
            "platform_python_implementation": python_implementation,
            "python_full_version": full_version,
            "python_version": f"{version[0]}.{version[1]}",
        }

        platform_tags: Sequence[str]
        if platform_spec is None:
            name = host_target.name
            platform_tags = host_target.platform_tags
            arch = host_target.arch
            glibc_version = host_target.glibc_version
            for key in (
                "os_name",
                "platform_machine",
                "platform_release",
                "platform_system",
                "platform_version",
                "sys_platform",
            ):
                marker_environment[key] = host_target.marker_environment[key]
        else:
            name, platform_tags, arch, glibc_version, platform_markers = (
                _parse_platform_spec(platform_spec)
            )
            marker_environment.update(platform_markers)

        return cls(
            name=name,
            python_version=version,
            python_version_str=version_str,
            interpreter=implementation,
            platform_tags=platform_tags,
            abi_tags=_abi_tags(implementation, version),
            arch=arch,
            glibc_version=glibc_version,
            marker_environment=marker_environment,
            is_host=False,
        )


def _linux_markers(arch: str) -> Dict[str, str]:
    return {
        "os_name": "posix",
        "platform_machine": arch,
        "platform_release": "",
        "platform_system": "Linux",
        "platform_version": "",
        "sys_platform": "linux",
    }


def _parse_platform_spec(
    platform_spec: str,
) -> Tuple[str, Sequence[str], str, Optional[Tuple[int, int]], Dict[str, str]]:
    """Decompose a wheel platform tag.

    The accepted tags are the ones ``pip --platform`` accepts: ``manylinux_X_Y_<arch>``
    and the legacy ``manylinux1``, ``manylinux2010`` and ``manylinux2014`` names, plain
    ``linux_<arch>`` which accepts no manylinux wheels, ``macosx_X_Y_<arch>`` and the
    Windows tags ``win_amd64``, ``win32`` and ``win_arm64``.

    Returns:
        The normalized tag, the platform tags, the architecture, the glibc version
        and the platform related markers.
    """
    tag = platform_spec.strip().lower().replace("-", "_")
    canonical = LEGACY_ALIASES.get(tag, tag)

    manylinux_match = re.match(MANYLINUX_REGEX, canonical)
    if manylinux_match:
        major, minor, arch = manylinux_match.groups()
        return (
            tag,
            (f"linux_{arch}",),
            arch,
            (int(major), int(minor)),
            _linux_markers(arch),
        )

    linux_match = re.fullmatch(r"linux_(.+)", tag)
    if linux_match:
        arch = linux_match.group(1)
        return tag, (tag,), arch, None, _linux_markers(arch)

    macos_match = re.match(MACOSX_REGEX, tag)
    if macos_match:
        major, minor, arch = macos_match.groups()
        if arch == "universal2":
            arch = "arm64"
        if arch not in ("arm64", "x86_64"):
            raise ValueError(
                f"Unsupported macOS architecture {arch!r} in platform {platform_spec!r}"
            )
        return (
            tag,
            _mac_platform_tags((int(major), int(minor)), arch),
            arch,
            None,
            {
                "os_name": "posix",
                "platform_machine": arch,
                "platform_release": "",
                "platform_system": "Darwin",
                "platform_version": "",
                "sys_platform": "darwin",
            },
        )

    if tag in _WINDOWS_PLATFORMS:
        machine = _WINDOWS_PLATFORMS[tag]
        return (
            tag,
            (tag,),
            machine,
            None,
            {
                "os_name": "nt",
                "platform_machine": machine,
                "platform_release": "",
                "platform_system": "Windows",
                "platform_version": "",
                "sys_platform": "win32",
            },
        )

    raise ValueError(
        f"Unsupported platform {platform_spec!r}. Expected a wheel platform tag such as "
        "manylinux_2_28_x86_64, manylinux2014_aarch64, macosx_11_0_arm64, "
        "macosx_10_15_x86_64, win_amd64 or win_arm64."
    )


def _manylinux_override(major: int, minor: int, arch: str) -> Optional[bool]:
    """Check the `_manylinux` module for a compatibility override on the host."""
    try:
        import _manylinux  # type: ignore  # pylint: disable=bad-option-value,import-outside-toplevel
    except ImportError:
        return None

    if hasattr(_manylinux, "manylinux_compatible"):
        # pylint: disable=no-member
        result = _manylinux.manylinux_compatible(major, minor, arch)
        if result is not None:
            return bool(result)
        return None
    if (major, minor) == (2, 5) and hasattr(_manylinux, "manylinux1_compatible"):
        # pylint: disable=no-member
        return bool(_manylinux.manylinux1_compatible)
    if (major, minor) == (2, 12) and hasattr(_manylinux, "manylinux2010_compatible"):
        # pylint: disable=no-member
        return bool(_manylinux.manylinux2010_compatible)
    return None


_HOST: Optional[TargetEnvironment] = None


def host() -> TargetEnvironment:
    """The cached description of the interpreter running req-compile."""
    global _HOST  # pylint: disable=global-statement
    if _HOST is None:
        _HOST = TargetEnvironment.host()
    return _HOST


def resolve(target: Optional[TargetEnvironment]) -> TargetEnvironment:
    """Default a possibly missing target to the host."""
    if target is None:
        return host()
    return target
