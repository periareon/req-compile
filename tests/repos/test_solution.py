import os
import tempfile

import pkg_resources
import pytest

import qer.compile
from qer.dists import DistInfo

from qer.repos.solution import SolutionRepository, load_from_file


def test_solution_repo():
    solution_repo = SolutionRepository(os.path.join(os.path.dirname(__file__), '..', 'solutionfile.txt'))
    result, cached = solution_repo.get_candidate(pkg_resources.Requirement.parse('pylint'))
    assert result.version == pkg_resources.parse_version('1.9.4')
    assert cached


def _get_node_strs(nodes):
    return set(node.key for node in nodes)


def test_load_solution(load_solution):
    result = load_solution('solutionfile.txt')

    assert _get_node_strs(result['six'].reverse_deps) == {'astroid', 'pylint'}
    assert _get_node_strs(result['astroid'].reverse_deps) == {'pylint'}
    assert _get_node_strs(result['pylint'].reverse_deps) == set()

    assert set(result['pylint'].metadata.reqs) == {
        pkg_resources.Requirement.parse('six'),
        pkg_resources.Requirement.parse('colorama'),
        pkg_resources.Requirement.parse('astroid>=1.6,<2.0'),
        pkg_resources.Requirement.parse('mccabe'),
        pkg_resources.Requirement.parse('isort>=4.2.5'),
    }

    assert set(result['astroid'].metadata.requires()) == {
        pkg_resources.Requirement.parse('six'),
        pkg_resources.Requirement.parse('lazy-object-proxy'),
        pkg_resources.Requirement.parse('wrapt'),
    }


def test_load_solution_extras(load_solution):
    result = load_solution('solutionfile_extras.txt')

    assert _get_node_strs(result['docpkg'].reverse_deps) == {'a[docs]', 'b'}
    assert _get_node_strs(result['pytest'].reverse_deps) == {'a[test]'}


def test_load_solution_fuzzywuzzy_extras(load_solution):
    result = load_solution('solutionfile_fuzzywuzzy_extras.txt')

    assert _get_node_strs(result['python-Levenshtein'].reverse_deps) == {'fuzzywuzzy[speedup]'}

    assert set(result['fuzzywuzzy'].metadata.requires()) == set()
    assert set(result['fuzzywuzzy'].metadata.requires('speedup')) == {
        pkg_resources.Requirement.parse('python-Levenshtein>=0.12 ; extra=="speedup"'),
    }


def test_load_remove_root_removes_all(load_solution):
    result = load_solution('solutionfile.txt')

    result.remove_dists(result['pylint'])

    assert len(result.nodes) == 0


@pytest.mark.parametrize('scenario, roots', [
    ('normal', ['a', 'd']),
    ('normal', ['a[x1]']),
])
def test_round_trip(scenario, roots, mock_metadata, mock_pypi):
    mock_pypi.load_scenario('normal')

    results, nodes, _ = qer.compile.perform_compile({'test': pkg_resources.parse_requirements(roots)}, mock_pypi)

    fd, name = tempfile.mkstemp()
    for line in results.generate_lines(nodes):
        os.write(fd, '{}  # {}\n'.format(line[0], line[1]).encode('utf-8'))
    os.close(fd)

    solution_result = load_from_file(name)
    for node in results:
        if isinstance(node.metadata, DistInfo):
            assert node.key in solution_result