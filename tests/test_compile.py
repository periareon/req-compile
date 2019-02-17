import os

import pkg_resources
import six

import qer.compile
import qer.pypi


def test_mock_pypi(mock_metadata, mock_pypi):
    mock_pypi('normal')

    assert qer.pypi.download_candidate('test') == (os.path.join('normal', 'test.METADATA'), False)


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
    mock_pypi('normal')

    results, cresults, root_mapping = qer.compile.perform_compile(
        [pkg_resources.Requirement.parse('c')], '.')

    assert list(_real_outputs(results)) == ['c==1.0.0']


def test_compile_b(mock_metadata, mock_pypi):
    mock_pypi('normal')

    results, cresults, root_mapping = qer.compile.perform_compile(
        [pkg_resources.Requirement.parse('b')], '.')

    assert _real_outputs(results) == ['b==1.1.0', 'c==1.0.0']


def test_compile_a(mock_metadata, mock_pypi):
    mock_pypi('normal')

    results, cresults, root_mapping = qer.compile.perform_compile(
        [pkg_resources.Requirement.parse('a')], '.')

    assert _real_outputs(results) == ['a==0.1.0']


def test_compile_a_extra(mock_metadata, mock_pypi):
    mock_pypi('normal')

    results, cresults, root_mapping = qer.compile.perform_compile(
        [pkg_resources.Requirement.parse('a[x1]')], '.')

    assert _real_outputs(results) == ['a[x1]==0.1.0', 'b==1.1.0', 'c==1.0.0']


def test_compile_a_b_c(mock_metadata, mock_pypi):
    mock_pypi('normal')

    results, cresults, root_mapping = qer.compile.perform_compile(
        pkg_resources.parse_requirements(['a', 'b', 'c']), '.')

    assert _real_outputs(results) == ['a==0.1.0', 'b==1.1.0', 'c==1.0.0']


def test_transitive_extra(mock_metadata, mock_pypi):
    mock_pypi('normal')

    results, cresults, root_mapping = qer.compile.perform_compile(
        pkg_resources.parse_requirements(['d']), '.')

    assert _real_outputs(results) == ['a[x1]==0.1.0', 'b==1.1.0', 'c==1.0.0', 'd==0.9.0']


def test_transitive_extra_with_normal(mock_metadata, mock_pypi):
    mock_pypi('normal')

    results, cresults, root_mapping = qer.compile.perform_compile(
        pkg_resources.parse_requirements(['a', 'd']), '.')

    assert _real_outputs(results) == ['a[x1]==0.1.0', 'b==1.1.0', 'c==1.0.0', 'd==0.9.0']


def test_combine_transitive_extras(mock_metadata, mock_pypi):
    mock_pypi('normal')

    results, cresults, root_mapping = qer.compile.perform_compile(
        pkg_resources.parse_requirements(['e', 'd']), '.')

    assert _real_outputs(results) == ['a[x1,x2]==0.1.0', 'b==1.1.0', 'c==1.0.0',
                                      'd==0.9.0', 'e==0.9.0', 'f==1.0.0']


def test_multiple_extras_in_root(mock_metadata, mock_pypi):
    mock_pypi('normal')

    results, cresults, root_mapping = qer.compile.perform_compile(
        pkg_resources.parse_requirements(['a[x1,x2,x3]']), '.')

    assert _real_outputs(results) == ['a[x1,x2,x3]==0.1.0', 'b==1.1.0', 'c==1.0.0',
                                      'f==1.0.0']


def test_multiple_extras_in_root(mock_metadata, mock_pypi):
    mock_pypi('normal')

    results, cresults, root_mapping = qer.compile.perform_compile(
        pkg_resources.parse_requirements(['a[x1,x2,x3]']), '.')

    assert _real_outputs(results) == ['a[x1,x2,x3]==0.1.0', 'b==1.1.0', 'c==1.0.0',
                                      'f==1.0.0']
