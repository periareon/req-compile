import os

import pkg_resources
import pytest

from qer.repos.source import SourceRepository


@pytest.fixture
def monorepo_dir():
    return os.path.join(os.path.dirname(__file__), 'monorepo')


def test_locate_source_package(monorepo_dir):
    source_repo = SourceRepository(monorepo_dir)
    result, cached = source_repo.get_candidate(pkg_resources.Requirement.parse('pkg2'))
    assert cached

    assert result.name == 'pkg2'


def test_nested_pkg(monorepo_dir):
    source_repo = SourceRepository(monorepo_dir)
    result, _ = source_repo.get_candidate(pkg_resources.Requirement.parse('pkg3'))
    assert result.name == 'pkg3'
