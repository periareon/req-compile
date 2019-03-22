import os

import pytest

from qer.solution import load_from_file


@pytest.fixture
def load_solution():
    def _load(filename):
        return load_from_file(os.path.join(os.path.dirname(__file__), filename))
    return _load


def test_load_solution(load_solution):
    result = load_solution('solutionfile.txt')

    assert list(result.dists['six'].sources.keys()) == ['astroid', 'pylint']
    assert list(result.dists['astroid'].sources.keys()) == ['pylint']
    assert list(result.dists['pylint'].sources.keys()) == []


def test_load_remove_root_removes_all(load_solution):
    result = load_solution('solutionfile.txt')

    result.remove_dist('pylint')

    assert len(result.dists) == 1
