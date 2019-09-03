import os
import pkg_resources

import responses
import pytest

from req_compile.repos.pypi import PyPIRepository

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
def test_python_requires(mocker, mocked_responses, tmpdir, read_contents, url_to_check):
    mocker.patch('req_compile.repos.repository.RequiresPython.SYS_PY_VERSION', pkg_resources.parse_version('3.7.12'))
    mocker.patch('req_compile.repos.repository.RequiresPython.SYS_PY_MAJOR', pkg_resources.parse_version('3'))
    mocker.patch('req_compile.repos.repository.RequiresPython.SYS_PY_MAJOR_MINOR', pkg_resources.parse_version('3.7'))
    mocker.patch('req_compile.repos.repository.RequiresPython.WHEEL_VERSION_TAGS', ('py3', 'cp37', 'py37'))

    wheeldir = str(tmpdir)
    mocked_responses.add(
        responses.GET, INDEX_URL + '/numpy/',
        body=read_contents('numpy.html'), status=200)

    repo = PyPIRepository(INDEX_URL, wheeldir)
    candidate = [candidate for candidate in repo.get_candidates(pkg_resources.Requirement.parse('numpy'))
                 if candidate.link[1] == url_to_check][0]
    assert candidate.py_version
    assert candidate.py_version.check_compatibility()
