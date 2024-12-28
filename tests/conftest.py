# pylint: disable=unused-variable,redefined-outer-name
import collections
import logging
import os
import sys
import tarfile
import tempfile
from typing import Callable, Iterable, NamedTuple, Optional, Tuple
from zipfile import ZipFile

import pkg_resources
import pytest
import pytest_mock

import req_compile.metadata
import req_compile.metadata.dist_info
import req_compile.metadata.metadata
import req_compile.utils
from req_compile.containers import RequirementContainer
from req_compile.repos.repository import Candidate, Repository
from req_compile.repos.solution import SolutionRepository


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
    # pylint: disable-next=unused-argument
    def _parse_metadata(filename, origin=None, extras=()):
        full_name = (
            filename
            if os.path.isabs(filename)
            else os.path.join(os.path.dirname(__file__), filename)
        )
        with open(full_name, "r", encoding="utf-8") as handle:
            # pylint: disable-next=protected-access
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
        super().__init__("mock")
        self.scenario = None
        self.index_map = None

    def load_scenario(self, scenario: str, limit_reqs=None) -> None:
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

    def _build_candidate(self, req: Optional[pkg_resources.Requirement]) -> Candidate:
        path = _to_path(self.scenario, req)
        full_name = (
            path
            if os.path.isabs(path)
            else os.path.join(os.path.dirname(__file__), path)
        )
        with open(full_name, "r", encoding="utf-8") as handle:
            # pylint: disable-next=protected-access
            metadata = req_compile.metadata.dist_info._parse_flat_metadata(
                handle.read()
            )

        assert req is not None

        return Candidate(
            req.project_name, path, metadata.version, None, None, "any", None
        )

    def get_candidates(
        self, req: Optional[pkg_resources.Requirement]
    ) -> Iterable[Candidate]:
        assert req, "Other Repository interfaces allow for None but not MockRepository"
        if self.index_map is None:
            return [self._build_candidate(req)]
        avail = self.index_map[req.name.lower()]
        return [self._build_candidate(req) for req in avail]

    def resolve_candidate(
        self, candidate: Candidate
    ) -> Tuple[RequirementContainer, bool]:
        metadata = req_compile.metadata.metadata.extract_metadata(
            candidate.filename, origin=self
        )
        metadata.hash = "sha256=123456"
        return (
            metadata,
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


@pytest.fixture
def mock_targz():
    files_to_delete = []

    def build_targz(relative_dir):
        directory = os.path.join(
            os.path.dirname(__file__), "source-packages", relative_dir
        )
        build_dir = tempfile.mkdtemp()

        archive_name = os.path.basename(relative_dir) + ".tar.gz"
        tar_archive = os.path.join(build_dir, archive_name)
        with tarfile.open(tar_archive, "w:gz") as tarf:
            for root, dirs, files in os.walk(directory):
                for each_dir in dirs:
                    full_path = os.path.join(root, each_dir)
                    tarf.add(
                        full_path,
                        recursive=False,
                        arcname=relative_dir
                        + "/"
                        + os.path.relpath(full_path, directory),
                    )
                for file in files:
                    full_path = os.path.join(root, file)
                    tarf.add(
                        os.path.realpath(full_path),
                        arcname=relative_dir
                        + "/"
                        + os.path.relpath(full_path, directory),
                    )

        files_to_delete.append(tar_archive)
        return tar_archive

    try:
        yield build_targz
    finally:
        for archive in files_to_delete:
            os.remove(archive)


@pytest.fixture
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
            for root, _, files in os.walk(directory):
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
        this_dir = os.path.abspath(os.path.dirname(__file__))

        repo = SolutionRepository(os.path.join(this_dir, filename))
        return repo.solution

    return _load


class VersionInfo(NamedTuple):
    major: int
    minor: int
    patch: int


@pytest.fixture
def mock_py_version(mocker: pytest_mock.MockerFixture) -> Callable[[str], None]:
    def _mock_version(version: str) -> None:
        split = version.split(".")
        assert len(split) > 2
        major_version = split.pop(0)
        minor_version = split.pop(0)
        patch_version = split.pop(0)
        if patch_version is None:
            patch_version = "0"

        abi_suffix = ""
        if (major_version, minor_version) == ("3", "7"):
            abi_suffix = "m"

            # TODO: Python3.7 tests used to have patch versions dropped
            # so that behavior is temporarily maintained here
            patch_version = "0"

        _, _, build_info = sys.version.partition(" ")

        mocker.patch(
            "sys.version_info",
            VersionInfo(int(major_version), int(minor_version), int(patch_version)),
        )
        mocker.patch(
            "sys.version",
            f"{major_version}.{minor_version}.{patch_version} {build_info}",
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
            pkg_resources.parse_version(f"{major_version}.{minor_version}"),
        )
        mocker.patch(
            "req_compile.repos.repository.ABI_TAGS",
            (f"abi{major_version}", f"cp{major_version}{minor_version}{abi_suffix}"),
        )

    return _mock_version
