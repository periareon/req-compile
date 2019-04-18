import os

import pytest

from qer.solution import load_from_file


@pytest.fixture
def load_solution():
    def _load(filename):
        return load_from_file(os.path.join(os.path.dirname(__file__), filename))
    return _load


# def test_load_solution(load_solution):
#     result = load_solution('solutionfile.txt')
#
#     assert result['six'].reverse_deps == {'astroid', 'pylint'}
#     assert result['astroid'].reverse_deps == {'pylint'}
#     assert result['pylint'].reverse_deps == set()
#
#
# def test_load_remove_root_removes_all(load_solution):
#     result = load_solution('solutionfile.txt')
#
#     result.remove_dists('pylint')
#
#     assert len(result.dists) == 1
