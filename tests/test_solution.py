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

    assert set(result.dists['six'].sources.keys()) == {'astroid', 'pylint'}
    assert set(result.dists['astroid'].sources.keys()) == {'pylint'}
    assert set(result.dists['pylint'].sources.keys()) == set()


def test_load_remove_root_removes_all(load_solution):
    result = load_solution('solutionfile.txt')

    result.remove_dists('pylint')

    assert len(result.dists) == 1
