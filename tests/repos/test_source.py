import os

import pkg_resources
import pytest

from req_compile.repos.repository import NoCandidateException
from req_compile.repos.source import SourceRepository


@pytest.fixture
def monorepo_dir():
    return os.path.join(os.path.dirname(__file__), "monorepo")


def test_locate_source_package(monorepo_dir):
    source_repo = SourceRepository(monorepo_dir)
    result, cached = source_repo.get_candidate(pkg_resources.Requirement.parse("pkg2"))
    assert cached

    assert result.name == "pkg2"


def test_nested_pkg(monorepo_dir):
    source_repo = SourceRepository(monorepo_dir)
    result, _ = source_repo.get_candidate(pkg_resources.Requirement.parse("pkg3"))
    assert result.name == "pkg3"


def test_special_init(monorepo_dir):
    """Verify that __init__.py stops recursion"""
    source_repo = SourceRepository(monorepo_dir)
    with pytest.raises(NoCandidateException):
        source_repo.get_candidate(pkg_resources.Requirement.parse("pkg5"))


def test_marker(monorepo_dir):
    """Verify that special marker files are respected"""
    source_repo = SourceRepository(monorepo_dir)
    result, _ = source_repo.get_candidate(pkg_resources.Requirement.parse("pkg4"))
    assert result.name == "pkg4"

    source_repo_marker = SourceRepository(monorepo_dir, marker_files=[".special_dir"])
    with pytest.raises(NoCandidateException):
        source_repo_marker.get_candidate(pkg_resources.Requirement.parse("pkg4"))


def test_exclude_dirs(monorepo_dir):
    """Test that that projects can be excluded by excluded paths"""
    source_repo = SourceRepository(
        monorepo_dir, excluded_paths=[os.path.join(monorepo_dir, "subdir")]
    )
    assert source_repo.get_candidates(pkg_resources.Requirement.parse("pkg1"))
    assert source_repo.get_candidates(pkg_resources.Requirement.parse("pkg4"))
    with pytest.raises(NoCandidateException):
        source_repo.get_candidate(pkg_resources.Requirement.parse("pkg3"))
