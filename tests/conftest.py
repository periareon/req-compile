import collections
import os

import pkg_resources
import pytest

import qer.metadata
from qer.pypi import NoCandidateException


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


@pytest.fixture
def mock_pypi(mocker):
    mocker.patch('qer.pypi.start_session')

    pkg_results = {}

    def _build_builder(scenario, index_map=None):
        if index_map:
            results = collections.defaultdict(list)
            for req in index_map:
               results[req.name].append(req)
            index_map = results

        def _build_metadata_path(project_name, specifier=None, **kwargs):
            if index_map is None:
                return _to_path(scenario, pkg_resources.Requirement.parse(project_name)), False
            avail = index_map[project_name]
            for pkg in avail:
                if specifier is None or specifier.contains(pkg.specs[0][1]):
                    return _to_path(scenario, pkg), False

            raise NoCandidateException()

        download_mock = mocker.patch('qer.pypi.download_candidate',
                                     side_effect=_build_metadata_path)

        def _register_pkg(project_name, results):
            pkg_results[project_name] = os.path.join(scenario, results), False
            return download_mock

        return _register_pkg
    return _build_builder


@pytest.fixture
def mock_metadata(mocker, metadata_provider):
    mocker.patch('qer.metadata.extract_metadata', side_effect=metadata_provider)
