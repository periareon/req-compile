import os
import sys
import six

import pkg_resources
import qer.metadata

def test_a_with_no_extra(metadata_provider):
    info = metadata_provider('normal/a.METADATA')
    assert info.name == 'a'
    assert info.version == pkg_resources.parse_version('0.1.0')
    assert list(info.requires()) == []


def test_a_with_extra(metadata_provider):
    info = metadata_provider('normal/a.METADATA', extras=('x1',))
    assert info.name == 'a'
    assert info.version == pkg_resources.parse_version('0.1.0')
    assert list(info.requires(('x1',))) == [pkg_resources.Requirement.parse("b (>1); extra == 'x1'")]


def test_a_with_wrong_extra(metadata_provider):
    info = metadata_provider('normal/a.METADATA', extras=('plop',))
    assert info.name == 'a'
    assert info.version == pkg_resources.parse_version('0.1.0')
    assert list(info.requires()) == []


def test_pylint_python(metadata_provider):
    info = metadata_provider('real/pylint-1.9.4.METADATA', extras=())
    assert info.name == 'pylint'
    assert info.version == pkg_resources.parse_version('1.9.4')

    expected_reqs = set()
    if six.PY2:
        if sys.platform == 'win32':
            expected_reqs = ['astroid (<2.0,>=1.6)',
                             'six',
                             'isort (>=4.2.5)',
                             'mccabe',
                             'singledispatch; python_version<"3.4"',
                             'configparser; python_version=="2.7"',
                             'backports.functools-lru-cache; python_version=="2.7"',
                             'colorama; sys_platform=="win32"']
        else:
            expected_reqs = ['astroid (<2.0,>=1.6)',
                             'six',
                             'isort (>=4.2.5)',
                             'mccabe',
                             'singledispatch; python_version<"3.4"',
                             'configparser; python_version=="2.7"',
                             'backports.functools-lru-cache; python_version=="2.7"']
    else:
        if sys.platform == 'win32':
            expected_reqs = ['astroid (<2.0,>=1.6)',
                             'six',
                             'isort (>=4.2.5)',
                             'mccabe',
                             'colorama; sys_platform=="win32"']
        else:
            expected_reqs = ['astroid (<2.0,>=1.6)',
                             'six',
                             'isort (>=4.2.5)',
                             'mccabe']
    assert set(info.requires()) == set(pkg_resources.parse_requirements(expected_reqs))


def test_extract_tar(mock_targz):
    tar_archive = mock_targz('tar-1.0.0')

    metadata = qer.metadata.extract_metadata(tar_archive)
    assert metadata.name == 'tar'
    assert metadata.version == pkg_resources.parse_version('1.0.0')


def test_extract_tar_utf8(mock_targz):
    tar_archive = mock_targz('tar-utf8-1.1.0')

    metadata = qer.metadata.extract_metadata(tar_archive)
    assert metadata.name == 'tar-utf8'
    assert metadata.version == pkg_resources.parse_version('1.1.0')


def test_extract_print(mock_targz):
    tar_archive = mock_targz('print-1.1.0b8')

    metadata = qer.metadata.extract_metadata(tar_archive)
    assert metadata.name == 'print'
    assert metadata.version == pkg_resources.parse_version('1.1.0b8')


def test_pint(mock_zip):
    zip_archive = mock_zip('pint-0.6')

    metadata = qer.metadata.extract_metadata(zip_archive)
    assert metadata.name == 'Pint'
    assert metadata.version == pkg_resources.parse_version('0.6')


def test_wuc(mock_zip):
    zip_archive = mock_zip('wuc-0.5')

    metadata = qer.metadata.extract_metadata(zip_archive)
    assert metadata.name == 'win_unicode_console'
    assert metadata.version == pkg_resources.parse_version('0.5')


def test_pt(mock_targz):
    archive = mock_targz('pt-2.0.0')

    metadata = qer.metadata.extract_metadata(archive)
    assert metadata.name == 'pathtools'
    assert metadata.version == pkg_resources.parse_version('2.0.0')


def test_pyreadline(mock_zip):
    archive = mock_zip('pyreadline-2.1')

    metadata = qer.metadata.extract_metadata(archive)
    assert metadata.name == 'pyreadline'
    assert metadata.version == pkg_resources.parse_version('2.1')


def test_etxmlf(mock_targz):
    archive = mock_targz('etxmlf-1.0.1')

    metadata = qer.metadata.extract_metadata(archive)
    assert metadata.name == 'etxmlf'
    assert metadata.version == pkg_resources.parse_version('1.0.1')


def test_post(mock_targz):
    archive = mock_targz('post-3.2.1-1')

    metadata = qer.metadata.extract_metadata(archive)
    assert metadata.name == 'post'
    assert metadata.version == pkg_resources.parse_version('3.2.1-1')
