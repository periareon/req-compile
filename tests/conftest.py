import collections
import logging
import os

import pkg_resources
import pytest

import qer.metadata
from qer.repository import NoCandidateException
from qer.repository import Repository, Candidate


@pytest.fixture
def metadata_provider():
    def _parse_metadata(filename, extras=()):
        full_name = filename if os.path.isabs(filename) else os.path.join(os.path.dirname(__file__), filename)
        with open(full_name, 'r') as handle:
            return qer.metadata._parse_flat_metadata(handle.read(), extras=extras)
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
        if req.specs:
            version = req.specs[0][1]
        return Candidate(req.project_name,
                         _to_path(self.scenario, req),
                         pkg_resources.parse_version(version),
                         (), 'any', None)

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
def mock_pypi(mocker):
    return MockRepository()


@pytest.fixture
def mock_metadata(mocker, metadata_provider):
    mocker.patch('qer.metadata.extract_metadata', side_effect=metadata_provider)
