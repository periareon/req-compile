import os

import pkg_resources
import pytest
from pytest import fixture

import qer.compile
import qer.repos.pypi
import qer.repos.repository
import qer.utils
from qer.repos.multi import MultiRepository
from qer.repos.source import SourceRepository


def test_mock_pypi(mock_metadata, mock_pypi):
    mock_pypi.load_scenario('normal',
                            pkg_resources.parse_requirements(
                                ['test==1.0.0']))

    metadata, cached = mock_pypi.get_candidate(pkg_resources.Requirement.parse('test'))
    assert metadata.name == 'test'
    assert metadata.version == qer.utils.parse_version('1.0.0')


def _real_outputs(results):
    outputs = results[0].build(results[1])
    outputs = sorted(outputs, key=lambda x: x.name)
    return [str(req) for req in outputs]


@fixture
def perform_compile(mock_metadata, mock_pypi):
    def _compile(scenario, index, reqs, constraint_reqs=None):
        if index is not None:
            index = [pkg_resources.Requirement.parse(req) for req in index]
        mock_pypi.load_scenario(scenario, index)
        if constraint_reqs is not None:
            constraint_reqs = {'test_constraints': [pkg_resources.Requirement.parse(req) for req in constraint_reqs]}
        else:
            constraint_reqs = {}

        if isinstance(reqs, list):
            reqs = {'test_reqs': reqs}

        input_reqs = {key: [pkg_resources.Requirement.parse(req) for req in value] for key, value in reqs.items()}
        return _real_outputs(qer.compile.perform_compile(
            input_reqs,
            mock_pypi,
            constraint_reqs=constraint_reqs))
    return _compile


@pytest.mark.parametrize(
    'scenario, index, reqs, constraints, results',
    [
        ('normal', None, ['c'], None, ['c==1.0.0']),
        ('normal', None, ['b'], None, ['b==1.1.0', 'c==1.0.0']),
        ('normal', None, ['a'], None, ['a==0.1.0']),
        ('normal', None, ['a[x1]'], None, ['a[x1]==0.1.0', 'b==1.1.0', 'c==1.0.0']),
        ('normal', None, ['a', 'b', 'c'], None, ['a==0.1.0', 'b==1.1.0', 'c==1.0.0']),
        ('normal', None, ['d'], None, ['a[x1]==0.1.0', 'b==1.1.0', 'c==1.0.0', 'd==0.9.0']),
        ('normal', None, ['e', 'd'], None, ['a[x1,x2]==0.1.0', 'b==1.1.0', 'c==1.0.0', 'd==0.9.0', 'e==0.9.0', 'f==1.0.0']),
        ('normal', None, ['a[x1,x2,x3]'], None, ['a[x1,x2,x3]==0.1.0', 'b==1.1.0', 'c==1.0.0', 'f==1.0.0']),

        ('multi', ['x==1.0.0', 'x==0.9.0'], ['x<1'], None, ['x==0.9.0']),
        # Test that top level pins apply regardless of source
        ('multi', ['x==1.0.0', 'x==0.9.0'], {'a.txt': ['x'], 'b.txt': ['x<1']}, None, ['x==0.9.0']),
        # Check for a transitive pin violation
        ('multi', ['x==1.0.0', 'x==0.9.0', 'y==5.0.0', 'y==4.0.0'], {'a.txt': ['x', 'y'], 'b.txt': ['y<5']}, None, ['x==0.9.0', 'y==4.0.0']),
        ('multi', ['x==1.0.0', 'x==0.9.0'], ['x'], ['x<1'], ['x==0.9.0']),
        ('multi', ['x==1.0.0', 'x==0.9.0', 'y==5.0.0', 'y==4.0.0'], ['x==1'], ['y==5'], ['x==1.0.0']),

        ('walk-back', ['a==4.0', 'a==3.6', 'b==1.1', 'b==1.0'], ['a<3.7', 'b'], None, ['a==3.6', 'b==1.0']),

        ('early-violated', ['a==5.0.0', 'x==0.9.0', 'x==1.1.0', 'y==4.0.0', 'z==1.0.0'], ['a', 'y'], None, ['a==5.0.0', 'x==0.9.0', 'y==4.0.0', 'z==1.0.0']),

        ('extra-violated', ['a==5.0.0', 'b==4.0.0', 'x==0.9.0', 'x==1.1.0', 'y==4.0.0', 'z==1.0.0'], ['a', 'y'], None, ['a==5.0.0', 'b==4.0.0', 'x[test]==0.9.0', 'y==4.0.0', 'z==1.0.0']),
        ('extra-violated', ['a==5.0.0', 'b==4.0.0', 'x==0.9.0', 'x==1.1.0', 'y==4.0.0', 'z==1.0.0'], ['z', 'y'], None, ['x[test]==0.9.0', 'y==4.0.0', 'z==1.0.0']),

        ('repeat-violated', ['a==5.0.0', 'x==1.2.0', 'x==1.1.0', 'x==0.9.0', 'y==4.0.0'], ['a', 'x', 'y'], None, ['a==5.0.0', 'x==0.9.0', 'y==4.0.0']),
    ])
def test_simple_compile(perform_compile, scenario, index, reqs, constraints, results):
    assert perform_compile(scenario, index, reqs, constraint_reqs=constraints) == results


@pytest.mark.parametrize(
    'scenario, index, reqs, constraints',
    [
        ('multi', ['x==1.0.0'], ['x==1.0.1'], None),
        ('multi', ['y==5.0.0'], ['y'], None),
        ('multi', ['x==1.0.0'], ['x'], ['x<1']),
        ('multi', ['x==1.0.0', 'x==0.9.0', 'y==5.0.0', 'y==4.0.0'], ['y==5'], ['x>1'])
    ])
def test_no_candidate(perform_compile, scenario, index, reqs, constraints):
    with pytest.raises(qer.repos.repository.NoCandidateException):
        perform_compile(scenario, index, reqs, constraint_reqs=constraints)


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
    results = qer.compile.perform_compile({'test': [pkg_resources.Requirement.parse('user1')]}, local_tree)
    assert _real_outputs(results) == ['framework==1.0.1', 'user1==2.0.0']


def test_compile_source_user2(local_tree):
    results = qer.compile.perform_compile({'test': [pkg_resources.Requirement.parse('user-2')]}, local_tree)
    assert _real_outputs(results) == ['framework==1.0.1', 'user-2==1.1.0', 'util==8.0.0']


def test_compile_source_user2_recursive_root():
    base_dir = os.path.join(os.path.dirname(__file__), 'local-tree')
    repo = SourceRepository(base_dir)
    results = qer.compile.perform_compile({'test': [pkg_resources.Requirement.parse('user-2')]}, repo)
    assert _real_outputs(results) == ['framework==1.0.1', 'user-2==1.1.0', 'util==8.0.0']
