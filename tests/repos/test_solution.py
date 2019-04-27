import os

import pkg_resources

from qer.repos.solution import SolutionRepository


def test_solution_repo():
    solution_repo = SolutionRepository(os.path.join(os.path.dirname(__file__), '..', 'solutionfile.txt'))
    result, cached = solution_repo.get_candidate(pkg_resources.Requirement.parse('pylint'))
    assert result.version == pkg_resources.parse_version('1.9.4')
    assert cached
