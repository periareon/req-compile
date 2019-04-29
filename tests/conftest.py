import collections
import logging
import os
from zipfile import ZipFile

import pkg_resources
import pytest

import tarfile
import tempfile

import qer.metadata
from qer.repos.repository import RequiresPython
from qer.repos.repository import Repository, Candidate
from qer.repos.solution import load_from_file


@pytest.fixture
def metadata_provider():
    def _parse_metadata(filename, origin=None, extras=()):
        full_name = filename if os.path.isabs(filename) else os.path.join(os.path.dirname(__file__), filename)
        with open(full_name, 'r') as handle:
            return qer.metadata._parse_flat_metadata(handle.read())
    return _parse_metadata


def _to_path(scenario, req):
    if req.specs:
        specific_path = os.path.join(os.path.dirname(__file__), scenario,
                                     req.name + '-' + req.specs[0][1] + '.METADATA')
        if os.path.exists(specific_path):
            return specific_path
    return os.path.join(scenario, req.name + '.METADATA')


class MockRepository(Repository):
    def __init__(self):
        super(MockRepository, self).__init__()
        self.scenario = None
        self.index_map = None

    def source_of(self, req):
        return self

    def load_scenario(self, scenario, index_map=None):
        self.scenario = scenario
        if index_map:
            results = collections.defaultdict(list)
            for req in index_map:
               results[req.name].append(req)
            index_map = results

        self.index_map = index_map

    def _build_candidate(self, req):
        version = ''
        path = _to_path(self.scenario, req)
        full_name = path if os.path.isabs(path) else os.path.join(os.path.dirname(__file__), path)
        with open(full_name, 'r') as handle:
            metadata = qer.metadata._parse_flat_metadata(handle.read())

        return Candidate(req.project_name,
                         path,
                         metadata.version,
                         RequiresPython(None), 'any', None)

    def get_candidates(self, req):
            if self.index_map is None:
                return [self._build_candidate(req)]
            avail = self.index_map[req.name]
            return [self._build_candidate(req) for req in avail]

    def resolve_candidate(self, candidate):
        return candidate.filename, False

    @property
    def logger(self):
        return logging.getLogger('')

    def close(self):
        pass


@pytest.fixture
def mock_pypi():
    return MockRepository()


@pytest.fixture
def mock_metadata(mocker, metadata_provider):
    mocker.patch('qer.metadata.extract_metadata', side_effect=metadata_provider)


@pytest.yield_fixture
def mock_targz():
    files_to_delete = []

    def build_targz(directory):
        directory = os.path.join(os.path.dirname(__file__), 'source-packages', directory)
        build_dir = tempfile.mkdtemp()

        archive_name = os.path.basename(directory) + '.tar.gz'
        tar_archive = os.path.join(build_dir, archive_name)
        with tarfile.open(tar_archive, 'w:gz') as tarf:
            tarf.add(directory, arcname=os.path.basename(directory))

        files_to_delete.append(tar_archive)
        return tar_archive

    yield build_targz

    for archive in files_to_delete:
        os.remove(archive)


@pytest.yield_fixture
def mock_zip():
    files_to_delete = []

    def build_zip(directory):
        directory = os.path.join(os.path.dirname(__file__), 'source-packages', directory)
        build_dir = tempfile.mkdtemp()

        archive_name = os.path.basename(directory) + '.zip'
        zip_archive = os.path.join(build_dir, archive_name)

        with ZipFile(zip_archive, 'w') as handle:
            handle.write(directory, arcname=os.path.basename(directory))
            for root, dirs, files in os.walk(directory):
                for file in files:
                    full_path = os.path.join(root, file)

                    handle.write(full_path, arcname=os.path.join(os.path.basename(directory), os.path.relpath(full_path, directory)))

        files_to_delete.append(zip_archive)
        return zip_archive

    yield build_zip

    for archive in files_to_delete:
        os.remove(archive)


@pytest.fixture
def mock_source():
    def build_source(directory):
        directory = os.path.join(os.path.dirname(__file__), 'source-packages', directory)
        return directory
    return build_source


@pytest.fixture
def load_solution():
    def _load(filename):
        return load_from_file(os.path.join(os.path.dirname(__file__), filename))
    return _load
