import pkg_resources
import pytest

from qer.repos.repository import RequiresPython


@pytest.fixture
def mock_py_version(mocker):
    def _mock_version(version):
        major_version = version.split('.')[0]
        minor_version = version.split('.')[1]
        mocker.patch('qer.repos.repository.RequiresPython.SYS_PY_VERSION',
                     pkg_resources.parse_version(version))
        mocker.patch('qer.repos.repository.RequiresPython.SYS_PY_MAJOR',
                     pkg_resources.parse_version(major_version))
        mocker.patch('qer.repos.repository.RequiresPython.SYS_PY_MAJOR_MINOR',
                     pkg_resources.parse_version('.'.join(version.split('.')[:2])))
        mocker.patch('qer.repos.repository.RequiresPython.WHEEL_VERSION_TAGS',
                     ('py' + major_version, 'py' + major_version + minor_version))
    return _mock_version


@pytest.mark.parametrize('sys_py_version, py_requires', [
    ('2.7.15', '>=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*'),
    ('3.6.4', '>=2.7,!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*'),
    ('3.5.0', '==3.5'),
    ('3.2.17', '>=2.7, ==3.*'),
    ('3.5.0', None),
    ('2.6.10', None),
    ('3.6.3', ('py3',)),
    ('3.6.3', ('py2', 'py3')),
    ('3.6.3', ())
])
def test_requires_python_compatible(mock_py_version, sys_py_version, py_requires):
    mock_py_version(sys_py_version)
    assert RequiresPython(py_requires).check_compatibility()


@pytest.mark.parametrize('sys_py_version, py_requires', [
    ('2.6.2', '>=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*'),
    ('3.2.17', '>=2.7,!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*'),
    ('3.2.17', '>=2.7, !=3.*'),
    ('3.6.3', ('py2',)),
    ('2.7.16', ('py3',)),
])
def test_requires_python_incompatible(mock_py_version, sys_py_version, py_requires):
    mock_py_version(sys_py_version)
    assert not RequiresPython(py_requires).check_compatibility()


@pytest.mark.parametrize('py_requires, expected', [
    (('py2',), 'py2'),
    (('py2', 'py3'), 'py2,py3'),
    (('py3', 'py2'), 'py2,py3'),
    ((), 'any'),
    (None, 'any'),
    ('>=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*', '')
])
def test_requires_python_str(py_requires, expected):
    assert str(RequiresPython(py_requires)) == expected
