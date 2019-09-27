import os
import sys

import pytest
import six

import pkg_resources

import req_compile.extractor
import req_compile.metadata


def test_a_with_no_extra(metadata_provider):
    info = metadata_provider('normal/a.METADATA')
    assert info.name == 'a'
    assert info.version == pkg_resources.parse_version('0.1.0')
    assert list(info.requires()) == []


def test_parse_flat_metadata_extra_space():
    results = req_compile.metadata._parse_flat_metadata(open(os.path.join(os.path.dirname(__file__),
                                                                          'METADATA-extra-space')).read())
    assert results.requires() == [pkg_resources.Requirement.parse('django')]


def test_a_with_extra(metadata_provider):
    info = metadata_provider('normal/a.METADATA')
    assert info.name == 'a'
    assert info.version == pkg_resources.parse_version('0.1.0')
    assert list(info.requires('x1')) == [pkg_resources.Requirement.parse("b (>1); extra == 'x1'")]


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


@pytest.mark.parametrize('filename,result_name,result_version', [
                         ['post-2.3.1-2.tar.gz', 'post', '2.3.1-2'],
                         ['pytest-ui-0.3b0.linux-x86_64.tar.gz', 'pytest-ui', '0.3beta0'],
                         ['backports-thing-1.0.1.tar.gz', 'backports-thing', '1.0.1'],
                         ['backports-thing-1.0.1.tar.gz', 'backports-thing', '1.0.1'],
                         ['project-v1.0.tar.gz', 'project', '1.0'],
                         ['pyvmomi-5.5.0.2014.1.1.tar.gz', 'pyvmomi', '5.5.0.2014.1.1'],
                         ['pyvmomi-5.5.0-2014.1.1.tar.gz', 'pyvmomi', '5.5.0-2014.1.1'],
                         ['python-project-3-0.0.1.tar.gz', 'python-project-3', '0.0.1'],
                         ['python-project-v2-0.1.1.tar.gz', 'python-project-v2', '0.1.1'],
])
def test_parse_source_filename(filename, result_name, result_version):
    result = req_compile.metadata.parse_source_filename(filename)
    assert result == (result_name, pkg_resources.parse_version(result_version))


def test_extract_tar(mock_targz):
    tar_archive = mock_targz('tar-1.0.0')

    metadata = req_compile.metadata.extract_metadata(tar_archive)
    assert metadata.name == 'tar'
    assert metadata.version == pkg_resources.parse_version('1.0.0')


def test_extract_tar_utf8(mock_targz):
    tar_archive = mock_targz('tar-utf8-1.1.0')

    metadata = req_compile.metadata.extract_metadata(tar_archive)
    assert metadata.name == 'tar-utf8'
    assert metadata.version == pkg_resources.parse_version('1.1.0')


def test_extract_print(mock_targz):
    tar_archive = mock_targz('print-1.1.0b8')

    try:
        metadata = req_compile.metadata.extract_metadata(tar_archive)
    except req_compile.metadata.MetadataError:
        assert False

    assert metadata.name == 'print'
    assert metadata.version == pkg_resources.parse_version('1.1.0b8')


def test_pint(mock_zip):
    zip_archive = mock_zip('pint-0.6')

    metadata = req_compile.metadata.extract_metadata(zip_archive)
    assert metadata.name == 'Pint'
    assert metadata.version == pkg_resources.parse_version('0.6')


def test_wuc(mock_zip):
    zip_archive = mock_zip('wuc-0.5')

    metadata = req_compile.metadata.extract_metadata(zip_archive)
    assert metadata.name == 'win_unicode_console'
    assert metadata.version == pkg_resources.parse_version('0.5')


def test_pt(mock_targz):
    archive = mock_targz('pt-2.0.0')

    metadata = req_compile.metadata.extract_metadata(archive)
    assert metadata.name == 'pathtools'
    assert metadata.version == pkg_resources.parse_version('2.0.0')


def test_termcolor(mock_targz):
    archive = mock_targz('termcolor-1.1.0')

    metadata = req_compile.metadata.extract_metadata(archive)
    assert metadata.name == 'termcolor'
    assert metadata.version == pkg_resources.parse_version('1.1.0')


def test_pyreadline(mock_zip):
    archive = mock_zip('pyreadline-2.1')

    metadata = req_compile.metadata.extract_metadata(archive)
    assert metadata.name == 'pyreadline'
    assert metadata.version == pkg_resources.parse_version('2.1')


def test_et_xmlfile(mock_targz):
    archive = mock_targz('et_xmlfile-1.0.1')

    metadata = req_compile.metadata.extract_metadata(archive)
    assert metadata.name == 'et_xmlfile'
    assert metadata.version == pkg_resources.parse_version('1.0.1')


def test_compound(mock_targz):
    """Test one tar after another directly that have failed in the passed"""
    archive = mock_targz('et_xmlfile-1.0.1')
    req_compile.metadata.extract_metadata(archive)

    archive = mock_targz('ed-1.4')
    req_compile.metadata.extract_metadata(archive)


def test_ed(mock_targz):
    archive = mock_targz('ed-1.4')

    metadata = req_compile.metadata.extract_metadata(archive)
    assert metadata.name == 'ed'


def test_pyyaml(mock_targz):
    archive = mock_targz('PyYAML-5.1')

    metadata = req_compile.metadata.extract_metadata(archive)
    assert metadata.name == 'PyYAML'
    assert metadata.version == pkg_resources.parse_version('5.1')


def test_psutil(mock_targz):
    archive = mock_targz('psutil-5.6.2')

    metadata = req_compile.metadata.extract_metadata(archive)
    assert metadata.name == 'psutil'
    assert metadata.version == pkg_resources.parse_version('5.6.2')


def test_ptl(mock_targz):
    archive = mock_targz('ptl-2015.11.4')

    metadata = req_compile.metadata.extract_metadata(archive)
    assert metadata.name == 'ptl'
    assert metadata.version == pkg_resources.parse_version('2015.11.4')
    assert set(metadata.reqs) == set(pkg_resources.parse_requirements(['pytest>=2.8.1']))


def test_reloader(mock_targz):
    archive = mock_targz('reloader-1.0')

    metadata = req_compile.metadata.extract_metadata(archive)
    assert metadata.name == 'reloader'
    assert metadata.version == pkg_resources.parse_version('1.0')


def test_billiards(mock_targz):
    archive = mock_targz('billiard-3.6.0.0')

    metadata = req_compile.metadata.extract_metadata(archive)
    assert metadata.name == 'billiard'
    assert metadata.version == pkg_resources.parse_version('3.6.0.0')


def test_setup_with_tenacity(mock_targz):
    archive = mock_targz('setup-with-tenacity-1.0')

    metadata = req_compile.metadata.extract_metadata(archive)
    assert metadata.name == 'setup-with-tenacity'
    assert metadata.version == pkg_resources.parse_version('1.0')


def test_setup_with_tenacity_tornado(mock_targz):
    archive = mock_targz('setup-with-tenacity-tornado-1.0')

    metadata = req_compile.metadata.extract_metadata(archive)
    assert metadata.name == 'setup-with-tenacity-tornado'
    assert metadata.version == pkg_resources.parse_version('1.0')


def test_non_extractor():
    this_path = os.path.dirname(__file__)
    source_path = os.path.join(this_path, 'source-packages', 'comtypes-1.1.7')

    extractor = req_compile.extractor.NonExtractor(source_path)
    all_names = set(extractor.names())
    assert all_names == {
        'comtypes-1.1.7/README',
        'comtypes-1.1.7/setup.py',
        'comtypes-1.1.7/comtypes/__init__.py',
        'comtypes-1.1.7/test/setup.py'
    }


def test_pkg_with_cython(mock_source):
    path = mock_source('pkg-with-cython-1.0')

    metadata = req_compile.metadata.extract_metadata(path)
    assert metadata.name == 'pkg-with-cython'
    assert metadata.version == pkg_resources.parse_version('1.0')


def test_comtypes_as_source(mock_source):
    path = mock_source('comtypes-1.1.7')

    metadata = req_compile.metadata.extract_metadata(path)
    assert metadata.name == 'comtypes'
    assert metadata.version == pkg_resources.parse_version('1.1.7')


def test_self_source():
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

    metadata = req_compile.metadata.extract_metadata(path)
    assert metadata.name == 'req-compile'


def test_post_as_source(mock_source):
    archive = mock_source('post-3.2.1-1')

    metadata = req_compile.metadata.extract_metadata(archive)
    assert metadata.name == 'post'
    assert metadata.version == pkg_resources.parse_version('3.2.1-1')


def test_svn(mock_targz):
    archive = mock_targz('svn-0.3.46')

    metadata = req_compile.metadata.extract_metadata(archive)
    assert metadata.name == 'svn'
    assert metadata.version == pkg_resources.parse_version('0.3.46')
    assert metadata.reqs == list(pkg_resources.parse_requirements([
        'python-dateutil>=2.2',
        'nose']))


def test_path_exists(mock_targz):
    archive = mock_targz('path-exists-2.0')

    metadata = req_compile.metadata.extract_metadata(archive)
    assert metadata.name == 'path-exists'
    assert metadata.version == pkg_resources.parse_version('2.0')


# def test_future(mock_targz):
#     archive = mock_targz('future-0.17.4')
#
#     metadata = req_compile.metadata.extract_metadata(archive)
#     assert metadata.name == 'future'
#     assert metadata.version == pkg_resources.parse_version('0.17.4')


def test_dill(mock_targz):
    archive = mock_targz('dill-0.3.0')

    metadata = req_compile.metadata.extract_metadata(archive)
    assert metadata.name == 'dill'
    assert metadata.version == pkg_resources.parse_version('0.3.0')


def test_scapy(mock_targz):
    archive = mock_targz('scapy-2.4.0')

    metadata = req_compile.metadata.extract_metadata(archive)
    assert metadata.name == 'scapy'
    assert metadata.version == pkg_resources.parse_version('2.4.0')


def test_invalid_extra(mock_targz):
    archive = mock_targz('invalid-extra-2.1')

    metadata = req_compile.metadata.extract_metadata(archive)
    assert metadata.name == 'WTForms'
    assert metadata.version == pkg_resources.parse_version('2.1')


# def test_cerberus(mock_targz):
#     archive = mock_targz('cerberus-1.1')
#
#     metadata = req_compile.metadata.extract_metadata(archive)
#     assert metadata.name == 'Cerberus'
#     assert metadata.version == pkg_resources.parse_version('1.1')


# def test_pyusb(mock_targz):
#     archive = mock_targz('pyusb-1.0.2')
#
#     metadata = req_compile.metadata.extract_metadata(archive)
#     assert metadata.name == 'pyusb'
#     assert metadata.version == pkg_resources.parse_version('1.0.2')
