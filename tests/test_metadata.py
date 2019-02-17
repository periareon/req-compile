import sys
import six

import pkg_resources


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
