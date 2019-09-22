import os
import pkg_resources

import responses
import pytest

from req_compile.repos.repository import Candidate, WheelVersionTags, DistributionType
import req_compile.repos.pypi
from req_compile.repos.pypi import PyPIRepository, check_python_compatibility

INDEX_URL = 'https://pypi.org'


@pytest.fixture
def mocked_responses():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


@pytest.fixture
def read_contents():
    def _do_read(resource):
        with open(os.path.join(os.path.dirname(__file__), resource)) as handle:
            return handle.read()
    return _do_read


def test_successful_numpy(mocked_responses, tmpdir, read_contents):
    wheeldir = str(tmpdir)
    mocked_responses.add(
        responses.GET, INDEX_URL + '/numpy/',
        body=read_contents('numpy.html'), status=200)
    repo = PyPIRepository(INDEX_URL, wheeldir)

    candidates = repo.get_candidates(pkg_resources.Requirement.parse('numpy'))

    # The total is the total number of links - exe links, which we do not support
    assert len(candidates) == 1127 - 34
    assert len(mocked_responses.calls) == 1


def test_no_candidates(mocked_responses, tmpdir):
    wheeldir = str(tmpdir)
    mocked_responses.add(responses.GET, INDEX_URL + '/garbage/', status=404)
    repo = PyPIRepository(INDEX_URL, wheeldir)

    candidates = repo.get_candidates(pkg_resources.Requirement.parse('garbage'))

    assert candidates == []
    assert len(mocked_responses.calls) == 1


def test_resolve_new_numpy(mocked_responses, tmpdir, read_contents, mocker):
    wheeldir = str(tmpdir)
    mocked_responses.add(
        responses.GET, INDEX_URL + '/numpy/',
        body=read_contents('numpy.html'), status=200)

    repo = PyPIRepository(INDEX_URL, wheeldir)
    candidates = repo.get_candidates(pkg_resources.Requirement.parse('numpy'))
    for candidate in candidates:
        if '1.16.3' in candidate.link[1]:
            mocked_responses.add(
                responses.GET, candidate.link[1],
                body=read_contents('numpy.whl-contents'), status=200)

    with mocker.patch('req_compile.repos.pypi.extract_metadata'):
        candidate, cached = repo.get_candidate(pkg_resources.Requirement.parse('numpy'))
    assert candidate is not None
    assert not cached

    listing = tmpdir.listdir()
    assert len(listing) == 1
    assert '1.16.3' in str(listing[0])
    assert '.whl' in str(listing[0])

    # Query the index, and download
    assert len(mocked_responses.calls) == 2


@pytest.mark.parametrize('url_to_check', [
    'https://pypi.org/numpy-1.16.3-cp37-cp37m-win_amd64.whl#sha256=HASH',
    'https://pypi.org/numpy-1.16.3-cp37-cp37m-manylinux1_x86_64.whl#sha256=HASH',
    'https://pypi.org/numpy-1.16.3.zip#sha256=HASH'
])
def test_python_requires_wheel_tags(mocked_responses, tmpdir, mock_py_version, read_contents, url_to_check):
    mock_py_version('3.7.12')

    wheeldir = str(tmpdir)
    mocked_responses.add(
        responses.GET, INDEX_URL + '/numpy/',
        body=read_contents('numpy.html'), status=200)

    repo = PyPIRepository(INDEX_URL, wheeldir)
    candidate = [candidate for candidate in repo.get_candidates(pkg_resources.Requirement.parse('numpy'))
                 if candidate.link[1] == url_to_check][0]
    if candidate.py_version:
        assert candidate.py_version.check_compatibility()


@pytest.mark.parametrize('sys_py_version, py_requires', [
    ('2.7.15', '>=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*'),
    ('3.6.4', '>=2.7,!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*'),
    ('3.5.0', '==3.5'),
    ('3.2.17', '>=2.7, ==3.*'),
    ('3.5.4', '~=3.5'),
    ('3.7', '~=3'),
])
def test_requires_python_compatible(mock_py_version, sys_py_version, py_requires):
    mock_py_version(sys_py_version)
    assert check_python_compatibility(py_requires)


@pytest.mark.parametrize('sys_py_version, py_requires', [
    ('2.6.2', '>=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*'),
    ('3.2.17', '>=2.7,!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*'),
    ('3.2.17', '>=2.7, !=3.*'),
    ('4.1.0', '~=3.5'),
    ('2.7.2', '~=3.3'),
    ('2.7.2', '>=3.3,<4')
])
def test_requires_python_incompatible(mock_py_version, sys_py_version, py_requires):
    mock_py_version(sys_py_version)
    assert not check_python_compatibility(py_requires)


def test_links_parser_wheel():
    filename = 'pytest-4.3.0-py2.py3-none-any.whl'
    url = 'https://url'
    lp = req_compile.repos.pypi.LinksHTMLParser(url)
    lp.active_link = url, filename
    lp.handle_data(filename)
    assert lp.dists == [Candidate('pytest', filename, pkg_resources.parse_version('4.3.0'),
                                  WheelVersionTags(('py2', 'py3')), 'any', (url, filename), DistributionType.WHEEL)]


def test_links_py3_wheel():
    filename = 'PyVISA-1.9.1-py3-none-any.whl'
    url = 'https://url'
    lp = req_compile.repos.pypi.LinksHTMLParser(url)
    lp.active_link = url, filename
    lp.handle_data(filename)
    assert lp.dists == [Candidate('PyVISA', filename, pkg_resources.parse_version('1.9.1'), WheelVersionTags(('py3',)), 'any', (url, filename), DistributionType.WHEEL)]


def test_links_parser_tar_gz_hyph():
    filename = 'PyVISA-py-0.3.1.tar.gz'
    url = 'https://url'
    lp = req_compile.repos.pypi.LinksHTMLParser(url)
    lp.active_link = url, filename
    lp.handle_data(filename)
    assert lp.dists == [Candidate('PyVISA-py', filename, pkg_resources.parse_version('0.3.1'), None, 'any', (url, filename), DistributionType.SDIST)]


def test_tar_gz_dot():
    filename = 'backports.html-1.1.0.tar.gz'
    candidate = req_compile.repos.repository._tar_gz_candidate('test', filename)

    assert candidate == \
        Candidate('backports.html', filename, pkg_resources.parse_version('1.1.0'), None, 'any', 'test', DistributionType.SDIST)


def test_wheel_dot():
    filename = 'backports.html-1.1.0-py2.py3-none-any.whl'
    candidate = req_compile.repos.repository._wheel_candidate('test', filename)

    assert candidate == \
        Candidate('backports.html', filename,
                           pkg_resources.parse_version('1.1.0'), WheelVersionTags(('py2', 'py3')), 'any', 'test', DistributionType.WHEEL)


def test_wheel_platform_specific_tags():
    filename = 'pywin32-224-cp27-cp27m-win_amd64.whl'
    candidate = req_compile.repos.repository._wheel_candidate('test', filename)

    assert candidate == \
        Candidate('pywin32', filename,
                           pkg_resources.parse_version('224'), WheelVersionTags(('cp27',)), 'win_amd64', 'test', DistributionType.WHEEL)
