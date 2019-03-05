import os

import pkg_resources
import pytest
import six

import qer.compile
import qer.pypi
import qer.repository


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

    with pytest.raises(qer.repository.NoCandidateException):
        qer.compile.perform_compile(
            pkg_resources.parse_requirements(['x==1']),
            '.',
            mock_pypi,
            constraint_reqs=list(pkg_resources.parse_requirements(['y<5'])))
