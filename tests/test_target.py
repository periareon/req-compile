"""Tests for describing and compiling for environments other than the host."""

# pylint: disable=redefined-outer-name
import argparse
import sys

import pytest
from packaging.requirements import Requirement

import req_compile.target
from req_compile.cmdline import add_target_args, build_target
from req_compile.repos.pypi import check_python_compatibility
from req_compile.repos.repository import (
    CantUseReason,
    _wheel_filename_to_candidate,
    check_usability,
    filter_candidates,
    sort_candidates,
)
from req_compile.target import TargetEnvironment


def _wheel(tags: str, name: str = "pkg", version: str = "1.0") -> str:
    return f"{name}-{version}-{tags}.whl"


def _usable(wheel: str, target: TargetEnvironment):
    candidate = _wheel_filename_to_candidate("pypi", wheel)
    assert candidate is not None
    return check_usability(None, candidate, target=target)


@pytest.mark.parametrize(
    "spec, name, glibc, markers",
    [
        (
            "manylinux_2_28_x86_64",
            "manylinux_2_28_x86_64",
            (2, 28),
            {
                "sys_platform": "linux",
                "platform_system": "Linux",
                "platform_machine": "x86_64",
                "os_name": "posix",
            },
        ),
        (
            "manylinux2014_aarch64",
            "manylinux2014_aarch64",
            (2, 17),
            {"sys_platform": "linux", "platform_machine": "aarch64"},
        ),
        (
            "manylinux1_x86_64",
            "manylinux1_x86_64",
            (2, 5),
            {"sys_platform": "linux", "platform_machine": "x86_64"},
        ),
        (
            "linux_x86_64",
            "linux_x86_64",
            None,
            {"sys_platform": "linux", "platform_machine": "x86_64"},
        ),
        (
            "macosx_11_0_arm64",
            "macosx_11_0_arm64",
            None,
            {
                "sys_platform": "darwin",
                "platform_system": "Darwin",
                "platform_machine": "arm64",
                "os_name": "posix",
            },
        ),
        (
            "macosx_10_15_x86_64",
            "macosx_10_15_x86_64",
            None,
            {"sys_platform": "darwin", "platform_machine": "x86_64"},
        ),
        (
            "macosx-12-0-universal2",
            "macosx_12_0_universal2",
            None,
            {"sys_platform": "darwin", "platform_machine": "arm64"},
        ),
        (
            "win_amd64",
            "win_amd64",
            None,
            {
                "sys_platform": "win32",
                "platform_system": "Windows",
                "platform_machine": "AMD64",
                "os_name": "nt",
            },
        ),
        (
            "win32",
            "win32",
            None,
            {"sys_platform": "win32", "platform_machine": "x86"},
        ),
        (
            "win_arm64",
            "win_arm64",
            None,
            {"sys_platform": "win32", "platform_machine": "ARM64"},
        ),
    ],
)
def test_platform_specs(spec, name, glibc, markers):
    target = TargetEnvironment.from_spec(spec, python_version="3.11")
    assert target.name == name
    assert target.glibc_version == glibc
    assert not target.is_host
    for key, value in markers.items():
        assert target.marker_environment[key] == value, key
    assert target.marker_environment["python_version"] == "3.11"
    assert target.marker_environment["python_full_version"] == "3.11.0"
    assert target.marker_environment["implementation_name"] == "cpython"
    assert target.marker_environment["platform_python_implementation"] == "CPython"
    assert target.python_version == (3, 11, 0)
    assert target.python_version_str == "3.11"
    assert target.interpreter == "cp"
    assert target.abi_tags == ("abi3", "cp311")


def test_architecture_matches_marker():
    """`arch` is the machine as `uname` reports it, which is what the host records."""
    for spec, machine in [
        ("win_amd64", "AMD64"),
        ("win32", "x86"),
        ("win_arm64", "ARM64"),
        ("macosx_11_0_arm64", "arm64"),
        ("macosx_11_0_x86_64", "x86_64"),
        ("manylinux_2_28_aarch64", "aarch64"),
    ]:
        target = TargetEnvironment.from_spec(spec, "3.11")
        assert target.arch == machine, spec
        assert target.marker_environment["platform_machine"] == machine, spec


def test_python_version_only():
    """Only changing the Python version keeps the host platform."""
    host = req_compile.target.host()
    target = TargetEnvironment.from_spec(python_version="3.9.2")
    assert target.name == host.name
    assert target.platform_tags == host.platform_tags
    assert target.glibc_version == host.glibc_version
    assert target.marker_environment["sys_platform"] == sys.platform
    assert target.marker_environment["python_version"] == "3.9"
    assert target.marker_environment["python_full_version"] == "3.9.2"
    assert target.python_version == (3, 9, 2)
    assert target.interpreter == host.interpreter


def test_host():
    host = req_compile.target.host()
    assert host.is_host
    assert host.python_version == tuple(sys.version_info[:3])
    assert host.marker_environment["sys_platform"] == sys.platform
    assert TargetEnvironment.from_spec() is host
    # Spelling out the host's own version and implementation still describes the host.
    assert TargetEnvironment.from_spec(
        python_version=host.python_version_str, implementation=host.interpreter
    ).is_host
    assert not TargetEnvironment.from_spec(python_version="3.9.2").is_host
    # The name of the host is a platform tag describing it.
    described = TargetEnvironment.from_spec(host.name, host.python_version_str)
    assert described.platform_tags == host.platform_tags
    assert described.glibc_version == host.glibc_version
    assert described.arch == host.arch
    # Host and a target describing the host interpreter agree on wheel selection.
    for wheel in (
        _wheel("py3-none-any"),
        _wheel(f"cp{sys.version_info.major}{sys.version_info.minor}-abi3-any"),
        _wheel("cp27-cp27m-any"),
    ):
        assert _usable(wheel, host) == _usable(
            wheel, TargetEnvironment.from_spec(python_version=host.python_version_str)
        )


def test_implementation():
    target = TargetEnvironment.from_spec(
        "manylinux_2_28_x86_64", "3.10", implementation="pp"
    )
    assert target.marker_environment["implementation_name"] == "pypy"
    assert target.marker_environment["platform_python_implementation"] == "PyPy"
    assert target.abi_tags == ("abi3", "pp310")
    assert _usable(_wheel("pp310-pypy310_pp73-manylinux2014_x86_64"), target) is None
    assert (
        _usable(_wheel("pp39-pypy39_pp73-manylinux2014_x86_64"), target)
        == CantUseReason.WRONG_ABI
    )
    assert (
        _usable(_wheel("cp310-cp310-manylinux2014_x86_64"), target)
        == CantUseReason.WRONG_PYTHON_VERSION
    )


def test_abi3_before_python_38():
    target = TargetEnvironment.from_spec("manylinux_2_28_x86_64", "3.7")
    assert target.abi_tags == ("abi3", "cp37m")
    assert _usable(_wheel("cp37-cp37m-manylinux1_x86_64"), target) is None


@pytest.mark.parametrize(
    "spec",
    [
        "solaris",
        "manylinux_2_17_",
        "macosx_11_0_ppc",
        "musllinux_1_2_x86_64",
        "macos_aarch64",
        "windows_x86_64",
        "",
    ],
)
def test_invalid_platform(spec):
    with pytest.raises(ValueError):
        TargetEnvironment.from_spec(spec)


@pytest.mark.parametrize("version", ["3", "three", "3.x", "3.11.0.1"])
def test_invalid_python_version(version):
    with pytest.raises(ValueError):
        TargetEnvironment.from_spec("manylinux_2_28_x86_64", version)


def test_invalid_implementation():
    with pytest.raises(ValueError):
        TargetEnvironment.from_spec(
            "manylinux_2_28_x86_64", "3.11", implementation="cpython"
        )


def test_equality_and_hash():
    one = TargetEnvironment.from_spec("manylinux_2_28_x86_64", "3.11")
    two = TargetEnvironment.from_spec("MANYLINUX-2-28-x86_64", "3.11")
    three = TargetEnvironment.from_spec("manylinux_2_28_x86_64", "3.12")
    assert one == two
    assert hash(one) == hash(two)
    assert one != three
    assert one.replace() == one
    assert one.replace(name="other") != one
    with pytest.raises(TypeError):
        one.replace(unknown=1)


LINUX = TargetEnvironment.from_spec("manylinux_2_17_x86_64", "3.11")
LINUX_ARM = TargetEnvironment.from_spec("manylinux_2_17_aarch64", "3.11")
LINUX_NEW_GLIBC = TargetEnvironment.from_spec("manylinux_2_28_x86_64", "3.11")
LINUX_PLAIN = TargetEnvironment.from_spec("linux_x86_64", "3.11")
MACOS = TargetEnvironment.from_spec("macosx_11_0_arm64", "3.11")
MACOS_INTEL = TargetEnvironment.from_spec("macosx_11_0_x86_64", "3.11")
MACOS_OLD = TargetEnvironment.from_spec("macosx_10_14_x86_64", "3.11")
WINDOWS = TargetEnvironment.from_spec("win_amd64", "3.11")


@pytest.mark.parametrize(
    "tags, targets",
    [
        ("py3-none-any", [LINUX, LINUX_ARM, MACOS, MACOS_INTEL, WINDOWS]),
        ("cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64", [LINUX]),
        ("cp311-cp311-manylinux2014_x86_64", [LINUX]),
        ("cp311-cp311-manylinux1_x86_64", [LINUX]),
        ("cp311-cp311-manylinux_2_28_x86_64", [LINUX_NEW_GLIBC]),
        ("cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64", [LINUX_ARM]),
        ("cp311-cp311-linux_x86_64", [LINUX]),
        ("cp311-cp311-musllinux_1_2_x86_64", []),
        ("cp311-cp311-macosx_11_0_arm64", [MACOS]),
        ("cp311-cp311-macosx_10_9_universal2", [MACOS, MACOS_INTEL]),
        ("cp311-cp311-macosx_10_9_x86_64", [MACOS, MACOS_INTEL]),
        ("cp311-cp311-macosx_10_15_x86_64", [MACOS, MACOS_INTEL]),
        ("cp311-cp311-macosx_12_0_arm64", []),
        ("cp311-cp311-win_amd64", [WINDOWS]),
        ("cp311-cp311-win32", []),
        ("cp310-abi3-win_amd64", [WINDOWS]),
        ("cp312-cp312-win_amd64", []),
        ("cp39-abi3-manylinux2014_x86_64", [LINUX]),
        ("cp311-cp311-win_amd64.manylinux2014_x86_64", [LINUX, WINDOWS]),
    ],
)
def test_wheel_compatibility(tags, targets):
    all_targets = [LINUX, LINUX_ARM, LINUX_NEW_GLIBC, MACOS, MACOS_INTEL, WINDOWS]
    usable = [target for target in all_targets if _usable(_wheel(tags), target) is None]
    # Newer glibc targets accept everything the baseline does.
    expected = list(targets)
    if LINUX in expected and LINUX_NEW_GLIBC not in expected:
        expected.append(LINUX_NEW_GLIBC)
    assert {t.name + str(t.glibc_version) for t in usable} == {
        t.name + str(t.glibc_version) for t in expected
    }


def test_plain_linux_tag_accepts_no_manylinux():
    """`linux_x86_64` behaves like pip: only wheels built without manylinux match."""
    assert LINUX_PLAIN.glibc_version is None
    assert _usable(_wheel("cp311-cp311-linux_x86_64"), LINUX_PLAIN) is None
    assert (
        _usable(_wheel("cp311-cp311-manylinux2014_x86_64"), LINUX_PLAIN)
        == CantUseReason.WRONG_PLATFORM
    )


def test_macos_version_limit():
    assert _usable(_wheel("cp311-cp311-macosx_10_14_x86_64"), MACOS_OLD) is None
    assert (
        _usable(_wheel("cp311-cp311-macosx_10_15_x86_64"), MACOS_OLD)
        == CantUseReason.WRONG_PLATFORM
    )


def test_wrong_reasons():
    assert (
        _usable(_wheel("cp311-cp311-manylinux2014_x86_64"), MACOS)
        == CantUseReason.WRONG_PLATFORM
    )
    assert (
        _usable(_wheel("cp312-cp312-manylinux2014_x86_64"), LINUX)
        == CantUseReason.WRONG_PYTHON_VERSION
    )
    assert (
        _usable(_wheel("cp311-cp310-manylinux2014_x86_64"), LINUX)
        == CantUseReason.WRONG_ABI
    )


def test_select_best_wheel_per_target():
    wheels = [
        _wheel("py3-none-any"),
        _wheel("cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64"),
        _wheel("cp311-cp311-manylinux_2_28_x86_64"),
        _wheel("cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64"),
        _wheel("cp311-cp311-macosx_10_9_x86_64"),
        _wheel("cp311-cp311-macosx_11_0_arm64"),
        _wheel("cp311-cp311-macosx_11_0_universal2"),
        _wheel("cp311-cp311-win_amd64"),
    ]
    candidates = [_wheel_filename_to_candidate("pypi", wheel) for wheel in wheels]
    req = Requirement("pkg")

    def best(target):
        usable = filter_candidates(req, candidates, target=target)
        return sort_candidates(usable, target=target)[0].filename

    assert best(LINUX) == wheels[1]
    assert best(LINUX_NEW_GLIBC) == wheels[2]
    assert best(LINUX_ARM) == wheels[3]
    # A wheel for a newer macOS release outranks an older architecture specific one.
    assert best(MACOS_INTEL) == wheels[6]
    assert best(MACOS_OLD) == wheels[4]
    assert best(MACOS) == wheels[5]
    assert best(WINDOWS) == wheels[7]

    # Candidates are scored per target, so the same objects sort differently.
    assert best(MACOS) != best(MACOS_INTEL)


@pytest.mark.parametrize(
    "requires_python, target, expected",
    [
        (">=3.8", LINUX, True),
        (">=3.12", LINUX, False),
        ("<3.11", LINUX, False),
        ("==3.11.*", LINUX, True),
        ("~=3.10", TargetEnvironment.from_spec("linux_x86_64", "3.11.4"), True),
        (">=3.11.2", TargetEnvironment.from_spec("linux_x86_64", "3.11.1"), False),
    ],
)
def test_requires_python(requires_python, target, expected):
    assert check_python_compatibility(requires_python, target) == expected


def test_command_line_args():
    parser = argparse.ArgumentParser()
    add_target_args(parser)

    assert build_target(parser.parse_args([])) is None

    target = build_target(
        parser.parse_args(
            ["--platform", "macosx_11_0_arm64", "--python-version", "3.12"]
        )
    )
    assert target == MACOS.replace(
        python_version=(3, 12, 0),
        python_version_str="3.12",
        abi_tags=("abi3", "cp312"),
        marker_environment=dict(
            MACOS.marker_environment,
            python_version="3.12",
            python_full_version="3.12.0",
            implementation_version="3.12.0",
        ),
    )

    target = build_target(parser.parse_args(["--python-version", "3.9"]))
    assert target is not None
    assert target.name == req_compile.target.host().name

    with pytest.raises(ValueError):
        build_target(parser.parse_args(["--platform", "plan9"]))
