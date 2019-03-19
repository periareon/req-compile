import os

import pkg_resources
import pytest
from pytest import fixture

import qer.compile
import qer.repos.pypi
import qer.repos.repository
from qer.repos.multi import MultiRepository
from qer.repos.source import SourceRepository


def test_mock_pypi(mock_metadata, mock_pypi):
    mock_pypi.load_scenario('normal',
                            pkg_resources.parse_requirements(
                                ['test==1.0.0']))

    assert mock_pypi.get_candidate(pkg_resources.Requirement.parse('test')) == (
        os.path.join('normal', 'test.METADATA'), False)


def _real_outputs(results):
    outputs = []
    for dist in results:
        if dist.metadata.name in qer.compile.BLACKLIST:
            continue
        if dist.metadata.name.startswith(qer.compile.ROOT_REQ):
            continue
        outputs.append(str(dist.metadata))
    return sorted(outputs)


def test_compile_c(mock_metadata, mock_pypi):
    mock_pypi.load_scenario('normal')

    results, cresults, root_mapping = qer.compile.perform_compile(
        [pkg_resources.Requirement.parse('c')], '.', mock_pypi)

    assert list(_real_outputs(results)) == ['c==1.0.0']


def test_compile_b(mock_metadata, mock_pypi):
    mock_pypi.load_scenario('normal')

    results, cresults, root_mapping = qer.compile.perform_compile(
        [pkg_resources.Requirement.parse('b')], '.', mock_pypi)

    assert _real_outputs(results) == ['b==1.1.0', 'c==1.0.0']


def test_compile_a(mock_metadata, mock_pypi):
    mock_pypi.load_scenario('normal')

    results, cresults, root_mapping = qer.compile.perform_compile(
        [pkg_resources.Requirement.parse('a')], '.', mock_pypi)

    assert _real_outputs(results) == ['a==0.1.0']


def test_compile_a_extra(mock_metadata, mock_pypi):
    mock_pypi.load_scenario('normal')

    results, cresults, root_mapping = qer.compile.perform_compile(
        [pkg_resources.Requirement.parse('a[x1]')], '.', mock_pypi)

    assert _real_outputs(results) == ['a[x1]==0.1.0', 'b==1.1.0', 'c==1.0.0']


def test_compile_a_b_c(mock_metadata, mock_pypi):
    mock_pypi.load_scenario('normal')

    results, cresults, root_mapping = qer.compile.perform_compile(
        pkg_resources.parse_requirements(['a', 'b', 'c']), '.', mock_pypi)

    assert _real_outputs(results) == ['a==0.1.0', 'b==1.1.0', 'c==1.0.0']


def test_transitive_extra(mock_metadata, mock_pypi):
    mock_pypi.load_scenario('normal')

    results, cresults, root_mapping = qer.compile.perform_compile(
        pkg_resources.parse_requirements(['d']), '.', mock_pypi)

    assert _real_outputs(results) == ['a[x1]==0.1.0', 'b==1.1.0', 'c==1.0.0', 'd==0.9.0']


def test_transitive_extra_with_normal(mock_metadata, mock_pypi):
    mock_pypi.load_scenario('normal')

    results, cresults, root_mapping = qer.compile.perform_compile(
        pkg_resources.parse_requirements(['a', 'd']), '.', mock_pypi)

    assert _real_outputs(results) == ['a[x1]==0.1.0', 'b==1.1.0', 'c==1.0.0', 'd==0.9.0']


def test_combine_transitive_extras(mock_metadata, mock_pypi):
    mock_pypi.load_scenario('normal')

    results, cresults, root_mapping = qer.compile.perform_compile(
        pkg_resources.parse_requirements(['e', 'd']), '.', mock_pypi)

    assert _real_outputs(results) == ['a[x1,x2]==0.1.0', 'b==1.1.0', 'c==1.0.0',
                                      'd==0.9.0', 'e==0.9.0', 'f==1.0.0']


def test_multiple_extras_in_root(mock_metadata, mock_pypi):
    mock_pypi.load_scenario('normal')

    results, cresults, root_mapping = qer.compile.perform_compile(
        pkg_resources.parse_requirements(['a[x1,x2,x3]']), '.', mock_pypi)

    assert _real_outputs(results) == ['a[x1,x2,x3]==0.1.0', 'b==1.1.0', 'c==1.0.0',
                                      'f==1.0.0']


def test_constrained_req(mock_metadata, mock_pypi):
    mock_pypi.load_scenario('multi',
                            pkg_resources.parse_requirements(
                                ['x==1.0.0',
                                 'x==0.9.0']))

    results, cresults, root_mapping = qer.compile.perform_compile(
        pkg_resources.parse_requirements(['x<1']), '.', mock_pypi)

    assert _real_outputs(results) == ['x==0.9.0']


def test_top_level_pins(mock_metadata, mock_pypi):
    mock_pypi.load_scenario('multi',
                            pkg_resources.parse_requirements(
                                ['x==1.0.0',
                                 'x==0.9.0']))

    results, cresults, root_mapping = qer.compile.perform_compile(
        {'a.txt': pkg_resources.parse_requirements(['x']),
         'b.txt': pkg_resources.parse_requirements(['x<1'])}, '.', mock_pypi)

    assert _real_outputs(results) == ['x==0.9.0']


def test_transitive_pin_violation(mock_metadata, mock_pypi):
    mock_pypi.load_scenario('multi',
                            pkg_resources.parse_requirements(
                                ['x==1.0.0',
                                 'x==0.9.0',
                                 'y==5.0.0',
                                 'y==4.0.0']))

    results, cresults, root_mapping = qer.compile.perform_compile(
        {'a.txt': pkg_resources.parse_requirements(['x', 'y']),
         'b.txt': pkg_resources.parse_requirements(['y<5'])}, '.', mock_pypi)

    assert _real_outputs(results) == ['x==0.9.0', 'y==4.0.0']


def test_compile_with_constraint(mock_metadata, mock_pypi):
    mock_pypi.load_scenario('multi',
                            pkg_resources.parse_requirements(
                                ['x==1.0.0',
                                 'x==0.9.0']))

    results, cresults, root_mapping = qer.compile.perform_compile(
        pkg_resources.parse_requirements(['x']),
        '.',
        mock_pypi,
        constraint_reqs=list(pkg_resources.parse_requirements(['x<1'])))

    assert _real_outputs(results) == ['x==0.9.0']


def test_compile_with_constraint_not_in_reqs(mock_metadata, mock_pypi):
    mock_pypi.load_scenario('multi',
                            pkg_resources.parse_requirements(
                                ['x==1.0.0',
                                 'x==0.9.0',
                                 'y==5.0.0',
                                 'y==4.0.0']))

    results, cresults, root_mapping = qer.compile.perform_compile(
        pkg_resources.parse_requirements(['x==1']),
        '.',
        mock_pypi,
        constraint_reqs=list(pkg_resources.parse_requirements(['y==5'])))

    assert _real_outputs(results) == ['x==1.0.0']


def test_compile_with_constraint_not_possible(mock_metadata, mock_pypi):
    mock_pypi.load_scenario('multi',
                            pkg_resources.parse_requirements(
                                ['x==1.0.0',
                                 'x==0.9.0',
                                 'y==5.0.0',
                                 'y==4.0.0']))

    with pytest.raises(qer.repos.repository.NoCandidateException):
        qer.compile.perform_compile(
            pkg_resources.parse_requirements(['x==1']),
            '.',
            mock_pypi,
            constraint_reqs=list(pkg_resources.parse_requirements(['y<5'])))


def test_compile_early_violated(mock_metadata, mock_pypi):
    mock_pypi.load_scenario('early-violated',
                            pkg_resources.parse_requirements(
                                ['a==5.0.0',
                                 'x==0.9.0',
                                 'x==1.1.0',
                                 'y==4.0.0',
                                 'z==1.0.0']))

    results, cresults, root_mapping = qer.compile.perform_compile(
        pkg_resources.parse_requirements(['a', 'y']),
        '.',
        mock_pypi)

    assert _real_outputs(results) == ['a==5.0.0', 'x==0.9.0', 'y==4.0.0', 'z==1.0.0']


def test_extra_violated(mock_metadata, mock_pypi):
    """When a violated requirement is required with an extra and transitively requires another
    dist, make sure that dist is not removed when required by another dist"""
    mock_pypi.load_scenario('extra-violated',
                            pkg_resources.parse_requirements(
                                ['a==5.0.0',
                                 'b==4.0.0',
                                 'x==0.9.0',
                                 'x==1.1.0',
                                 'y==4.0.0',
                                 'z==1.0.0']))

    results, cresults, root_mapping = qer.compile.perform_compile(
        pkg_resources.parse_requirements(['a', 'y']),
        '.',
        mock_pypi)

    assert _real_outputs(results) == ['a==5.0.0', 'b==4.0.0', 'x[test]==0.9.0', 'y==4.0.0', 'z==1.0.0']


def test_extra_violated_transitive_removed(mock_metadata, mock_pypi):
    """When a violated requirement is required with an extra and used to transitively require another
    package but no longer does, verify it does not appear in the output"""
    mock_pypi.load_scenario('extra-violated',
                            pkg_resources.parse_requirements(
                                ['a==5.0.0',
                                 'b==4.0.0',
                                 'x==0.9.0',
                                 'x==1.1.0',
                                 'y==4.0.0',
                                 'z==1.0.0']))

    results, cresults, root_mapping = qer.compile.perform_compile(
        pkg_resources.parse_requirements(['z', 'y']),
        '.',
        mock_pypi)

    assert _real_outputs(results) == ['x[test]==0.9.0', 'y==4.0.0', 'z==1.0.0']


def test_compile_repeat_violated(mock_metadata, mock_pypi):
    mock_pypi.load_scenario('repeat-violated',
                            pkg_resources.parse_requirements(
                                ['a==5.0.0',
                                 'x==1.2.0',
                                 'x==1.1.0',
                                 'x==0.9.0',
                                 'y==4.0.0']))

    results, cresults, root_mapping = qer.compile.perform_compile(
        pkg_resources.parse_requirements(['a', 'x', 'y']),
        '.',
        mock_pypi)

    assert _real_outputs(results) == ['a==5.0.0', 'x==0.9.0', 'y==4.0.0']


@fixture
def local_tree():
    base_dir = os.path.join(os.path.dirname(__file__), 'local-tree')
    source_repos = [
        SourceRepository(os.path.join(base_dir, 'framework')),
        SourceRepository(os.path.join(base_dir, 'user1')),
        SourceRepository(os.path.join(base_dir, 'user2')),
        SourceRepository(os.path.join(base_dir, 'util')),
    ]

    multi_repo = MultiRepository(*source_repos)
    return multi_repo


def test_compile_source_user1(local_tree):
    results, cresults, root_mapping = qer.compile.perform_compile([pkg_resources.Requirement.parse('user1')], '.', local_tree)
    assert _real_outputs(results) == ['framework==1.0.1', 'user1==2.0.0']


def test_compile_source_user2(local_tree):
    results, cresults, root_mapping = qer.compile.perform_compile([pkg_resources.Requirement.parse('user-2')], '.', local_tree)
    assert _real_outputs(results) == ['framework==1.0.1', 'user-2==1.1.0', 'util==8.0.0']


def test_compile_source_user2_recursive_root():
    base_dir = os.path.join(os.path.dirname(__file__), 'local-tree')
    repo = SourceRepository(base_dir)
    results, cresults, root_mapping = qer.compile.perform_compile([pkg_resources.Requirement.parse('user-2')], '.', repo)
    assert _real_outputs(results) == ['framework==1.0.1', 'user-2==1.1.0', 'util==8.0.0']
