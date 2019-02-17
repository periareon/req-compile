import os

import pytest

import qer.metadata


@pytest.fixture
def metadata_provider():
    def _parse_metadata(filename, extras=()):
        full_name = filename if os.path.isabs(filename) else os.path.join(os.path.dirname(__file__), filename)
        with open(full_name, 'r') as handle:
            return qer.metadata._parse_flat_metadata(handle.read(), extras=extras)
    return _parse_metadata


@pytest.fixture
def mock_pypi(mocker):
    def _build_builder(scenario):
        def _build_metadata_path(project_name, *args, **kwargs):
            return os.path.join(scenario, project_name + '.METADATA'), False

        mocker.patch('qer.pypi.download_candidate', side_effect=_build_metadata_path)

    return _build_builder


@pytest.fixture
def mock_metadata(mocker, metadata_provider):
    mocker.patch('qer.metadata.extract_metadata', side_effect=metadata_provider)
