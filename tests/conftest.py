import collections
import logging
import os
from zipfile import ZipFile

import pkg_resources
import pytest

import tarfile
import tempfile

import req_compile.metadata
import req_compile.metadata.dist_info
import req_compile.metadata.metadata
import req_compile.utils
from req_compile.repos.repository import Repository, Candidate
from req_compile.repos.solution import load_from_file


@pytest.fixture(autouse=True)
def setup_logging(caplog):
    caplog.set_level(logging.DEBUG, logger="req_compile")


@pytest.fixture(scope="function", autouse=True)
def clear_caches():
    """Fixture to automatically clear the LRU cache for
    the requirement parsing cache"""
    req_compile.utils.parse_requirement.cache_clear()


@pytest.fixture
def metadata_provider():
    def _parse_metadata(filename, origin=None, extras=()):
        full_name = (
            filename
            if os.path.isabs(filename)
            else os.path.join(os.path.dirname(__file__), filename)
        )
        with open(full_name, "r") as handle:
            return req_compile.metadata.dist_info._parse_flat_metadata(handle.read())

    return _parse_metadata


def _to_path(scenario, req):
    if req.specs:
        specific_path = os.path.join(
            os.path.dirname(__file__),
            scenario,
            req.name.lower() + "-" + req.specs[0][1] + ".METADATA",
        )
        if os.path.exists(specific_path):
            return specific_path
    return os.path.join(scenario, req.name + ".METADATA")


class MockRepository(Repository):
    def __init__(self):
        super(MockRepository, self).__init__("mock")
        self.scenario = None
        self.index_map = None

    def load_scenario(self, scenario, limit_reqs=None):
        """
        Load a scenario from the tests directory into the repository

        Args:
            scenario: Name of the scenario to load
            limit_reqs: If provided, limit the domain to reqs that match this list
        """
        self.scenario = scenario

        scenario_dir = os.path.join(os.path.dirname(__file__), scenario)
        metadata_entries = os.listdir(scenario_dir)

        self.index_map = collections.defaultdict(list)
        for entry in metadata_entries:
            name = entry.split("-")[0]
            version = entry.rsplit(".", 1)[0].split("-")[1]
            req = pkg_resources.Requirement.parse("{}=={}".format(name, version))
            if limit_reqs is None or req in limit_reqs:
                self.index_map[entry.split("-")[0].lower()].append(req)

    def _build_candidate(self, req):
        path = _to_path(self.scenario, req)
        full_name = (
            path
            if os.path.isabs(path)
            else os.path.join(os.path.dirname(__file__), path)
        )
        with open(full_name, "r") as handle:
            metadata = req_compile.metadata.dist_info._parse_flat_metadata(
                handle.read()
            )

        return Candidate(
            req.project_name, path, metadata.version, None, None, "any", None
        )

    def get_candidates(self, req):
        if self.index_map is None:
            return [self._build_candidate(req)]
        avail = self.index_map[req.name.lower()]
        return [self._build_candidate(req) for req in avail]

    def resolve_candidate(self, candidate):
        return (
            req_compile.metadata.metadata.extract_metadata(
                candidate.filename, origin=self
            ),
            False,
        )

    def close(self):
        pass


@pytest.fixture
def mock_pypi():
    return MockRepository()


@pytest.fixture
def mock_metadata(mocker, metadata_provider):
    mocker.patch(
        "req_compile.metadata.metadata.extract_metadata", side_effect=metadata_provider
    )


@pytest.yield_fixture
def mock_targz():
    files_to_delete = []

    def build_targz(directory):
        directory = os.path.join(
            os.path.dirname(__file__), "source-packages", directory
        )
        build_dir = tempfile.mkdtemp()

        archive_name = os.path.basename(directory) + ".tar.gz"
        tar_archive = os.path.join(build_dir, archive_name)
        with tarfile.open(tar_archive, "w:gz") as tarf:
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
        directory = os.path.join(
            os.path.dirname(__file__), "source-packages", directory
        )
        build_dir = tempfile.mkdtemp()

        archive_name = os.path.basename(directory) + ".zip"
        zip_archive = os.path.join(build_dir, archive_name)

        with ZipFile(zip_archive, "w") as handle:
            handle.write(directory, arcname=os.path.basename(directory))
            for root, dirs, files in os.walk(directory):
                for file in files:
                    full_path = os.path.join(root, file)

                    handle.write(
                        full_path,
                        arcname=os.path.join(
                            os.path.basename(directory),
                            os.path.relpath(full_path, directory),
                        ),
                    )

        files_to_delete.append(zip_archive)
        return zip_archive

    yield build_zip

    for archive in files_to_delete:
        os.remove(archive)


@pytest.fixture
def mock_source():
    def build_source(directory):
        directory = os.path.join(
            os.path.dirname(__file__), "source-packages", directory
        )
        return directory

    return build_source


@pytest.fixture
def load_solution():
    def _load(filename):
        return load_from_file(os.path.join(os.path.dirname(__file__), filename))

    return _load


VersionInfo = collections.namedtuple("VersionInfo", "major,minor,patch")


@pytest.fixture
def mock_py_version(mocker):
    def _mock_version(version):
        major_version = version.split(".")[0]
        minor_version = version.split(".")[1]
        mocker.patch(
            "sys.version_info", VersionInfo(int(major_version), int(minor_version), 0)
        )
        mocker.patch(
            "req_compile.repos.pypi.SYS_PY_VERSION",
            pkg_resources.parse_version(version),
        )
        mocker.patch(
            "req_compile.repos.pypi.SYS_PY_MAJOR",
            pkg_resources.parse_version(major_version),
        )
        mocker.patch(
            "req_compile.repos.pypi.SYS_PY_MAJOR_MINOR",
            pkg_resources.parse_version(".".join(version.split(".")[:2])),
        )

    return _mock_version
