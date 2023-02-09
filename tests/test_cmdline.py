from io import StringIO
import os

import pkg_resources
import pytest

from req_compile.cmdline import _create_input_reqs, compile_main
from req_compile.containers import DistInfo
from req_compile.repos.findlinks import FindLinksRepository
from req_compile.repos.pypi import PyPIRepository
from req_compile.repos.solution import SolutionRepository
from req_compile.repos.source import SourceRepository


@pytest.fixture
def basic_compile_mock(mocker):
    perform_compile_mock = mocker.patch("req_compile.cmdline.perform_compile")
    result = mocker.MagicMock()
    result.generate_lines.return_value = [("line", "line")]
    perform_compile_mock.return_value = result, mocker.MagicMock()
    return perform_compile_mock


@pytest.fixture
def compile_mock(basic_compile_mock, mocker):
    mocker.patch("req_compile.cmdline._create_input_reqs")
    mocker.patch("os.path.exists")
    mocker.patch("os.listdir")
    mocker.patch("req_compile.repos.solution.SolutionRepository.load_from_file")
    mocker.patch("req_compile.repos.repository.filename_to_candidate")
    return basic_compile_mock


def test_multiple_sources(compile_mock):
    compile_main(
        [
            "requirements.txt",
            "--source",
            "1",
            "--source",
            "2",
            "--source",
            "3",
            "--no-index",
        ]
    )
    perform_compile_args = compile_mock.mock_calls[0][1]
    assert list(perform_compile_args[1]) == [
        SourceRepository("1"),
        SourceRepository("2"),
        SourceRepository("3"),
    ]


def test_resolution_order(compile_mock):
    compile_main(
        [
            "requirements.txt",
            "--source",
            "source 1",
            "--solution",
            "solution",
            "--source",
            "source 2",
            "--index-url",
            "index",
            "--find-links",
            "find-links",
        ]
    )

    perform_compile_args = compile_mock.mock_calls[0][1]
    assert list(perform_compile_args[1]) == [
        SolutionRepository("solution"),
        SourceRepository("source 1"),
        SourceRepository("source 2"),
        FindLinksRepository("find-links"),
        PyPIRepository("index", None),
    ]


def test_source_dirs_dont_hit_pypi(mocker, basic_compile_mock):
    mocker.patch("os.path.exists")
    metadata_mock = mocker.patch("req_compile.metadata.extract_metadata")
    metadata_mock.return_value = DistInfo("myproj", "1.0", ["unknown_req"])

    compile_main(["source/myproj"])
    perform_compile_args = basic_compile_mock.mock_calls[0][1]
    assert perform_compile_args[0][0].name == "myproj"


@pytest.fixture
def mock_stdin(mocker):
    fake_stdin = StringIO()

    def _write(value):
        fake_stdin.write(value)
        fake_stdin.seek(0, 0)

    mocker.patch("sys.stdin", fake_stdin)
    return _write


def test_stdin_paths(mock_stdin):
    """Verify that paths work correctly from stdin"""
    mono_dir = os.path.join(os.path.dirname(__file__), "repos", "monorepo")
    mono1 = os.path.join(mono_dir, "pkg1")
    mono2 = os.path.join(mono_dir, "pkg2")
    mono3 = os.path.join(mono_dir, "subdir", "pkg3")
    mock_stdin(mono1 + "\n" + mono2 + "\n" + mono3 + "\n")

    extra_sources = []
    result = _create_input_reqs("-", extra_sources)

    assert set(extra_sources) == {f"--source={mono1}", f"--source={mono2}", f"--source={mono3}"}
    assert set(result.reqs) == set(
        pkg_resources.parse_requirements(["pkg1==1.0.0", "pkg2==2.0.1", "pkg3==0.0.0"])
    )


def test_stdin_reqs(mock_stdin):
    """Verify that lists of requirements work correctly from stdin, including comment and blank lines"""
    mock_stdin("pytest\n# Comment\n\npytest-mock\n")

    extra_sources = []
    result = _create_input_reqs("-", extra_sources)

    assert extra_sources == []
    assert set(result.reqs) == set(
        pkg_resources.parse_requirements(["pytest", "pytest-mock"])
    )
