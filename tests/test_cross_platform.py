"""Compile the same requirements for several targets and check markers are honored."""

import pytest
from packaging.requirements import Requirement

import req_compile.compile
from req_compile.containers import DistInfo
from req_compile.target import TargetEnvironment

from .conftest import MockRepository


def _compile(target):
    repo = MockRepository(target=target)
    repo.load_scenario("cross-platform")
    results, roots = req_compile.compile.perform_compile(
        [DistInfo("test_reqs", None, [Requirement("app")], meta=True)], repo
    )
    assert results.target is target
    return {node.key for node in results.visit_nodes(roots)}


@pytest.mark.usefixtures("mock_metadata")
@pytest.mark.parametrize(
    "platform, python_version, implementation, expected",
    [
        ("manylinux_2_28_x86_64", "3.11", None, {"uvloop"}),
        ("manylinux2014_aarch64", "3.10", None, {"uvloop", "tomli", "armlib"}),
        ("macosx_11_0_arm64", "3.12", None, {"uvloop", "pyobjc", "armlib"}),
        ("macosx_10_15_x86_64", "3.12", None, {"uvloop", "pyobjc"}),
        ("win_amd64", "3.9", None, {"colorama", "tomli"}),
        ("manylinux_2_28_x86_64", "3.11", "pp", {"uvloop", "pypylib"}),
    ],
)
def test_compile_for_target(platform, python_version, implementation, expected):
    target = TargetEnvironment.from_spec(platform, python_version, implementation)
    assert _compile(target) == {"app"} | expected


@pytest.mark.usefixtures("mock_metadata")
def test_compile_for_host_matches_explicit_host():
    """Describing the host explicitly gives the same solution as the default."""
    host = req_compile.target.host()
    explicit = TargetEnvironment.from_spec(
        python_version=host.python_version_str, implementation=host.interpreter
    )
    assert _compile(host) == _compile(explicit)
