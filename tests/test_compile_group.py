"""Solutions compiled together resolve every project to a single version."""

# pylint: disable=unbalanced-tuple-unpacking

from typing import Iterable, Optional, Set, Tuple

import pytest
from packaging.requirements import Requirement

import req_compile.compile
from req_compile.containers import DistInfo
from req_compile.errors import (
    NoCandidateException,
    NoCommonVersionException,
    PinConflictException,
)
from req_compile.repos.repository import Candidate
from req_compile.target import TargetEnvironment
from req_compile.utils import parse_version

from .conftest import MockRepository

LINUX = TargetEnvironment.from_spec("manylinux_2_28_x86_64", "3.11")
WINDOWS = TargetEnvironment.from_spec("win_amd64", "3.11")


class PlatformRepository(MockRepository):
    """A mock index where some versions have no artifact for the target."""

    def __init__(
        self,
        target: TargetEnvironment,
        missing: Iterable[Tuple[str, str]] = (),
    ) -> None:
        super().__init__(target=target)
        self.load_scenario("group")
        self.missing: Set[Tuple[str, str]] = set(missing)

    def get_candidates(self, req: Optional[Requirement]) -> Iterable[Candidate]:
        return [
            candidate
            for candidate in super().get_candidates(req)
            if (candidate.name, str(candidate.version)) not in self.missing
        ]


def _roots(*reqs: str) -> Iterable[DistInfo]:
    return [
        DistInfo("requirements.in", None, [Requirement(req) for req in reqs], meta=True)
    ]


def _versions(results) -> Set[str]:
    dists, roots = results
    return {str(node) for node in dists.visit_nodes(roots)}


def _compile_group(repos, roots=None, **kwargs):
    return req_compile.compile.perform_compile_group(
        roots or _roots("app"), repos, **kwargs
    )


@pytest.mark.usefixtures("mock_metadata")
def test_platform_specific_packages_do_not_leak():
    """Targets only share versions, each still resolves its own dependencies."""
    linux, windows = _compile_group(
        [PlatformRepository(LINUX), PlatformRepository(WINDOWS)]
    )
    assert _versions(linux) == {"app==1.0.0", "pkg==2.0.0", "sub==2.0.0", "lib==2.0.0"}
    assert _versions(windows) == _versions(linux) | {"winonly==1.0.0"}


@pytest.mark.usefixtures("mock_metadata")
def test_version_missing_on_a_later_target_is_rejected_for_all():
    """Linux would pick lib 2.0, which Windows cannot install, so both use 1.0."""
    linux, windows = _compile_group(
        [
            PlatformRepository(LINUX),
            PlatformRepository(WINDOWS, missing=[("lib", "2.0.0")]),
        ]
    )
    assert "lib==1.0.0" in _versions(linux)
    assert "lib==1.0.0" in _versions(windows)


@pytest.mark.usefixtures("mock_metadata")
def test_version_missing_on_an_earlier_target_is_never_chosen():
    linux, windows = _compile_group(
        [
            PlatformRepository(LINUX, missing=[("lib", "2.0.0")]),
            PlatformRepository(WINDOWS),
        ]
    )
    assert "lib==1.0.0" in _versions(linux)
    assert "lib==1.0.0" in _versions(windows)


@pytest.mark.usefixtures("mock_metadata")
def test_pins_are_kept():
    """The versions of existing solutions are recycled for every target."""
    linux, windows = _compile_group(
        [PlatformRepository(LINUX), PlatformRepository(WINDOWS)],
        pins={"lib": parse_version("1.0.0"), "pkg": parse_version("1.0.0")},
    )
    expected = {"app==1.0.0", "pkg==1.0.0", "sub==2.0.0", "lib==1.0.0"}
    assert _versions(linux) == expected
    assert _versions(windows) == expected | {"winonly==1.0.0"}


@pytest.mark.usefixtures("mock_metadata")
def test_pins_only_apply_to_required_packages():
    linux, _ = _compile_group(
        [PlatformRepository(LINUX), PlatformRepository(WINDOWS)],
        pins={"winonly": parse_version("1.0.0"), "unused": parse_version("1.0.0")},
    )
    assert "winonly" not in linux[0]
    assert "unused" not in linux[0]


@pytest.mark.usefixtures("mock_metadata")
def test_unusable_pin_is_rejected():
    """A pin from an old solution that no longer has an artifact yields."""
    linux, windows = _compile_group(
        [
            PlatformRepository(LINUX, missing=[("lib", "1.0.0")]),
            PlatformRepository(WINDOWS),
        ],
        pins={"lib": parse_version("1.0.0")},
    )
    assert "lib==2.0.0" in _versions(linux)
    assert "lib==2.0.0" in _versions(windows)


@pytest.mark.usefixtures("mock_metadata")
def test_constraint_on_one_target_walks_back_the_dependent_everywhere():
    """Windows picks pkg 2.0 first, but Linux cannot use the sub 2.0 it needs.

    Rather than giving Linux a different sub, pkg is walked back to 1.0 for both.
    """
    windows, linux = _compile_group(
        [PlatformRepository(WINDOWS), PlatformRepository(LINUX)],
        roots=_roots("app", 'sub<2 ; sys_platform == "linux"'),
    )
    assert _versions(linux) == {"app==1.0.0", "pkg==1.0.0", "sub==1.0.0", "lib==2.0.0"}
    assert _versions(windows) == {
        "app==1.0.0",
        "pkg==1.0.0",
        "sub==1.0.0",
        "lib==2.0.0",
        "winonly==1.0.0",
    }


@pytest.mark.usefixtures("mock_metadata")
def test_no_common_version():
    """Each target can only use the version of lib the other cannot."""
    with pytest.raises(NoCommonVersionException) as exc_info:
        _compile_group(
            [
                PlatformRepository(LINUX, missing=[("lib", "1.0.0")]),
                PlatformRepository(WINDOWS, missing=[("lib", "2.0.0")]),
            ]
        )
    ex = exc_info.value
    assert ex.name == "lib"
    assert [(r.target.name, str(r.version)) for r in ex.rejections] == [
        ("win_amd64", "2.0.0"),
        ("manylinux_2_28_x86_64", "1.0.0"),
        # Linux can only use 2.0.0, which Windows rejected.
        ("manylinux_2_28_x86_64", "None"),
    ]
    assert "No version of lib can be used by every solution" in str(ex)


@pytest.mark.usefixtures("mock_metadata")
def test_missing_package_is_a_plain_failure():
    """A package no target can find is not reported as a disagreement."""
    with pytest.raises(NoCandidateException) as exc_info:
        _compile_group(
            [PlatformRepository(LINUX), PlatformRepository(WINDOWS)],
            roots=_roots("app", "nothing"),
        )
    assert not isinstance(exc_info.value, PinConflictException)
    assert exc_info.value.req.name == "nothing"


@pytest.mark.usefixtures("mock_metadata")
def test_single_target_matches_perform_compile():
    repo = PlatformRepository(LINUX)
    (grouped,) = _compile_group([repo])
    single = req_compile.compile.perform_compile(_roots("app"), repo)
    assert _versions(grouped) == _versions(single)


@pytest.mark.usefixtures("mock_metadata")
def test_soft_pin_conflict_is_a_no_candidate_exception():
    """Callers that only know `NoCandidateException` still get a failure."""
    repo = PlatformRepository(WINDOWS, missing=[("lib", "2.0.0")])
    with pytest.raises(PinConflictException) as exc_info:
        req_compile.compile.perform_compile(
            _roots("app"), repo, pins={"lib": Requirement("lib==2.0.0")}
        )
    ex = exc_info.value
    assert isinstance(ex, NoCandidateException)
    assert ex.name == "lib"
    assert ex.no_candidate
    assert str(ex) == "no candidate for lib==2.0.0"
    assert ex.results is not None


@pytest.mark.usefixtures("mock_metadata")
def test_soft_pin_conflicting_with_a_requirement():
    repo = PlatformRepository(LINUX)
    with pytest.raises(PinConflictException) as exc_info:
        req_compile.compile.perform_compile(
            _roots("app", "lib>=2"), repo, pins={"lib": Requirement("lib==1.0.0")}
        )
    ex = exc_info.value
    assert not ex.no_candidate
    assert str(ex) == "lib==1.0.0 conflicts with lib>=2"
