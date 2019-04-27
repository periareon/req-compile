import os

import pytest


def _get_node_strs(nodes):
    return set(node.key for node in nodes)


def test_load_solution(load_solution):
    result = load_solution('solutionfile.txt')

    assert _get_node_strs(result['six'].reverse_deps) == {'astroid', 'pylint'}
    assert _get_node_strs(result['astroid'].reverse_deps) == {'pylint'}
    assert _get_node_strs(result['pylint'].reverse_deps) == set()


def test_load_remove_root_removes_all(load_solution):
    result = load_solution('solutionfile.txt')

    result.remove_dists(result['pylint'])

    assert len(result.nodes) == 0
