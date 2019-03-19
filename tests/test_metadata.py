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


def test_parse_source_post_version():
    result = qer.metadata.parse_source_filename('post-2.3.1-2.tar.gz')
    assert result == ('post', pkg_resources.parse_version('2.3.1-2'))


def test_parse_source_dash_package_name():
    result = qer.metadata.parse_source_filename('backports-thing-1.0.1.tar.gz')
    assert result == ('backports-thing', pkg_resources.parse_version('1.0.1'))


def test_parse_source_dot_package_name():
    result = qer.metadata.parse_source_filename('backports.thing-1.0.1')
    assert result == ('backports.thing', pkg_resources.parse_version('1.0.1'))


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


def test_comtypes(mock_zip):
    archive = mock_zip('comtypes-1.1.7')

    metadata = qer.metadata.extract_metadata(archive)
    assert metadata.name == 'comtypes'
    assert metadata.version == pkg_resources.parse_version('1.1.7')


def test_noname(mock_targz):
    archive = mock_targz('noname-1.0')

    metadata = qer.metadata.extract_metadata(archive)
    assert metadata.name == 'noname'
    assert metadata.version == pkg_resources.parse_version('1.0')


def test_non_extractor():
    this_path = os.path.dirname(__file__)
    source_path = os.path.join(this_path, 'source-packages', 'comtypes-1.1.7')

    extractor = qer.metadata.NonExtractor(source_path)
    all_names = set(extractor.names())
    assert all_names == {
        'comtypes-1.1.7/README',
        'comtypes-1.1.7/setup.py',
        'comtypes-1.1.7/comtypes/__init__.py',
        'comtypes-1.1.7/test/setup.py'
    }


def test_comtypes_as_source(mock_source):
    path = mock_source('comtypes-1.1.7')

    metadata = qer.metadata.extract_metadata(path)
    assert metadata.name == 'comtypes'
    assert metadata.version == pkg_resources.parse_version('1.1.7')


def test_self_source():
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

    metadata = qer.metadata.extract_metadata(path)
    assert metadata.name == 'qer'


def test_post_as_source(mock_source):
    archive = mock_source('post-3.2.1-1')

    metadata = qer.metadata.extract_metadata(archive)
    assert metadata.name == 'post'
    assert metadata.version == pkg_resources.parse_version('3.2.1-1')


def test_svn(mock_targz):
    archive = mock_targz('svn-0.3.46')

    metadata = qer.metadata.extract_metadata(archive)
    assert metadata.name == 'svn'
    assert metadata.version == pkg_resources.parse_version('0.3.46')
    assert metadata.reqs == list(pkg_resources.parse_requirements([
        'python-dateutil>=2.2',
        'nose']))
