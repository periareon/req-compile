import os
from typing import Iterable, Optional, Tuple
from unittest import mock

import pkg_resources
import pytest
from pytest import fixture

import req_compile.compile
from req_compile.compile import AllOnlyBinarySet
from req_compile.containers import DistInfo, RequirementContainer
import req_compile.errors
from req_compile.repos.multi import MultiRepository
import req_compile.repos.pypi
import req_compile.repos.repository
from req_compile.repos.repository import Repository, Candidate, filename_to_candidate
from req_compile.repos.source import SourceRepository
import req_compile.utils
from req_compile.utils import normalize_project_name


def test_mock_pypi(mock_metadata, mock_pypi):
    mock_pypi.load_scenario("normal")

    metadata, cached = mock_pypi.get_dist(pkg_resources.Requirement.parse("test"))
    assert metadata.name == "test"
    assert metadata.version == req_compile.utils.parse_version("1.0.0")


def _real_outputs(results):
    outputs = results[0].build(results[1])
    outputs = sorted(outputs, key=lambda x: x.name)
    return set(str(req) for req in outputs)


@fixture
def perform_compile(mock_metadata, mock_pypi):
    def _compile(scenario, reqs, constraint_reqs=None, limit_reqs=None):
        mock_pypi.load_scenario(scenario, limit_reqs=limit_reqs)
        if constraint_reqs is not None:
            constraint_reqs = [
                DistInfo(
                    "test_constraints",
                    None,
                    [pkg_resources.Requirement.parse(req) for req in constraint_reqs],
                )
            ]

        if isinstance(reqs, list):
            reqs = {"test_reqs": reqs}

        input_reqs = [
            DistInfo(
                key,
                None,
                [pkg_resources.Requirement.parse(req) for req in value],
                meta=True,
            )
            for key, value in reqs.items()
        ]
        return _real_outputs(
            req_compile.compile.perform_compile(
                input_reqs, mock_pypi, constraint_reqs=constraint_reqs
            )
        )

    return _compile


@pytest.mark.parametrize(
    "scenario, reqs, constraints, results",
    [
        ("normal", ["c"], None, ["c==1.0.0"]),
        ("normal", ["b"], None, ["b==1.1.0", "c==1.0.0"]),
        ("normal", ["a"], None, ["a==0.1.0"]),
        ("normal", ["a[x1]"], None, ["a[x1]==0.1.0", "b==1.1.0", "c==1.0.0"]),
        ("normal", ["a", "b", "c"], None, ["a==0.1.0", "b==1.1.0", "c==1.0.0"]),
        ("normal", ["d"], None, ["a[x1]==0.1.0", "b==1.1.0", "c==1.0.0", "d==0.9.0"],),
        (
            "normal",
            ["e", "d"],
            None,
            [
                "a[x1,x2]==0.1.0",
                "b==1.1.0",
                "c==1.0.0",
                "d==0.9.0",
                "e==0.9.0",
                "f==1.0.0",
            ],
        ),
        (
            "normal",
            ["a[x1,x2,x3]"],
            None,
            ["a[x1,x2,x3]==0.1.0", "b==1.1.0", "c==1.0.0", "f==1.0.0"],
        ),
        ("multi", ["x<1"], None, ["x==0.9.0"]),
        # Test that top level pins apply regardless of source
        ("multi", {"a.txt": ["x"], "b.txt": ["x<1"]}, None, ["x==0.9.0"],),
        # Check for a transitive pin violation
        (
            "multi",
            {"a.txt": ["x", "y"], "b.txt": ["y<5"]},
            None,
            ["x==0.9.0", "y==4.0.0"],
        ),
        ("multi", ["x"], ["x<1"], ["x==0.9.0"]),
        ("multi", ["x==1"], ["y==5"], ["x==1.0.0"],),
        # Check that metadata that declares to requirements on the same dependency is processed correctly
        ("multi", ["z"], None, ["z==1.0.0", "y==4.0.0", "x==0.9.0"],),
        ("walk-back", ["a<3.7", "b"], None, ["a==3.6", "b==1.0"],),
        (
            "early-violated",
            ["a", "y"],
            None,
            ["a==5.0.0", "x==0.9.0", "y==4.0.0", "z==1.0.0"],
        ),
        (
            "extra-violated",
            ["a", "y"],
            None,
            ["a==5.0.0", "b==4.0.0", "x[test]==0.9.0", "y==4.0.0", "z==1.0.0"],
        ),
        (
            "extra-violated",
            ["z", "y"],
            None,
            ["x[test]==0.9.0", "y==4.0.0", "z==1.0.0"],
        ),
        (
            "repeat-violated",
            ["a", "x", "y"],
            None,
            ["a==5.0.0", "x==0.9.0", "y==4.0.0"],
        ),
        (
            "flask-like-walkback",
            ["flask", "jinja2<3"],
            None,
            ["Flask==1.1.4", "Werkzeug==1.0.1", "Jinja2==2.11.3"],
        ),
    ],
)
def test_simple_compile(perform_compile, scenario, reqs, constraints, results):
    assert perform_compile(scenario, reqs, constraint_reqs=constraints) == set(results)


@pytest.mark.parametrize(
    "scenario, index, reqs, constraints",
    [
        ("multi", ["x==1.0.0"], ["x==1.0.1"], None),
        ("multi", ["y==5.0.0"], ["y"], None),
        ("multi", ["x==1.0.0"], ["x"], ["x<1"]),
        ("multi", ["x==1.0.0", "x==0.9.0", "y==5.0.0", "y==4.0.0"], ["y==5"], ["x>1"]),
    ],
)
def test_no_candidate(perform_compile, scenario, index, reqs, constraints):
    with pytest.raises(req_compile.errors.NoCandidateException):
        perform_compile(scenario, reqs, constraint_reqs=constraints, limit_reqs=index)


@fixture
def local_tree():
    base_dir = os.path.join(os.path.dirname(__file__), "local-tree")
    source_repos = [
        SourceRepository(os.path.join(base_dir, "framework")),
        SourceRepository(os.path.join(base_dir, "user1")),
        SourceRepository(os.path.join(base_dir, "user2")),
        SourceRepository(os.path.join(base_dir, "util")),
    ]

    multi_repo = MultiRepository(*source_repos)
    return multi_repo


def test_compile_source_user1(local_tree):
    results = req_compile.compile.perform_compile(
        [DistInfo("test", None, [pkg_resources.Requirement.parse("user1")], meta=True)],
        local_tree,
    )
    assert _real_outputs(results) == {"framework==1.0.1", "user1==2.0.0"}


def test_compile_source_user2(local_tree):
    results = req_compile.compile.perform_compile(
        [
            DistInfo(
                "test", None, [pkg_resources.Requirement.parse("user-2")], meta=True
            )
        ],
        local_tree,
    )
    assert _real_outputs(results) == {
        "framework==1.0.1",
        "user-2==1.1.0",
        "util==8.0.0",
    }


def test_compile_source_user2_recursive_root():
    base_dir = os.path.join(os.path.dirname(__file__), "local-tree")
    repo = SourceRepository(base_dir)
    results = req_compile.compile.perform_compile(
        [
            DistInfo(
                "test", None, [pkg_resources.Requirement.parse("user-2")], meta=True
            )
        ],
        repo,
    )
    assert _real_outputs(results) == {
        "framework==1.0.1",
        "user-2==1.1.0",
        "util==8.0.0",
    }


class OnlyBinaryRepository(Repository):
    def get_candidates(
        self, req: Optional[pkg_resources.Requirement]
    ) -> Iterable[Candidate]:
        result = [
            filename_to_candidate(None, "test-2.0.0.tar.gz"),
            filename_to_candidate(None, "test-1.0.0-py2.py3-none-any.whl"),
        ]
        return result

    def resolve_candidate(
        self, candidate: Candidate
    ) -> Tuple[RequirementContainer, bool]:
        dist = mock.MagicMock(spec=RequirementContainer)
        dist.origin = None
        dist.name = candidate.name
        dist.version = candidate.version
        dist.meta = False
        dist.to_definition.return_value = candidate.name, candidate.version
        dist.hash = ""
        return dist, False


def test_only_binary_skips_source():
    """Verify the newer source dist is skipped."""
    repo = OnlyBinaryRepository("test", True)
    input = [DistInfo("-", None, [pkg_resources.Requirement.parse("test")])]
    results = req_compile.compile.perform_compile(input, repo,)
    assert _real_outputs(results) == {
        "test==2.0.0",
    }
    results = req_compile.compile.perform_compile(
        input, repo, only_binary={normalize_project_name("test")},
    )
    assert _real_outputs(results) == {
        "test==1.0.0",
    }
    results = req_compile.compile.perform_compile(
        input, repo, only_binary=AllOnlyBinarySet(),
    )
    assert _real_outputs(results) == {
        "test==1.0.0",
    }
