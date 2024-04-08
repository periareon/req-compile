# pylint: disable=protected-access
import os
import platform
import sys
from typing import Callable

import pkg_resources
import pytest

import req_compile.filename
import req_compile.metadata
import req_compile.metadata.dist_info
import req_compile.metadata.extractor
import req_compile.metadata.metadata
import req_compile.metadata.source


def test_a_with_no_extra(metadata_provider):
    info = metadata_provider("normal/a-1.0.0.METADATA")
    assert info.name == "a"
    assert info.version == pkg_resources.parse_version("0.1.0")
    assert not list(info.requires())


def test_parse_flat_metadata_extra_space():
    results = req_compile.metadata.dist_info._parse_flat_metadata(
        open(
            os.path.join(os.path.dirname(__file__), "METADATA-extra-space"),
            encoding="utf-8",
        ).read()
    )
    assert results.requires() == [pkg_resources.Requirement.parse("django")]


def test_parse_flat_metadata_two_names():
    results = req_compile.metadata.dist_info._parse_flat_metadata(
        open(
            os.path.join(os.path.dirname(__file__), "METADATA-two-names"),
            encoding="utf-8",
        ).read()
    )
    assert results.name == "fabio"


def test_parse_flat_metadata_bizarre_extra():
    results = req_compile.metadata.dist_info._parse_flat_metadata(
        open(
            os.path.join(os.path.dirname(__file__), "METADATA-bizarre-extra"),
            encoding="utf-8",
        ).read()
    )
    assert results.name == "setuptools"
    assert not list(results.requires())
    assert results.requires(extra="ssl:sys_platform=='win32'")[0].name == "wincertstore"


def test_parse_flat_metadata_complex_marker(
    mock_py_version: Callable[[str], None]
) -> None:
    mock_py_version("3.7.12")

    results = req_compile.metadata.dist_info._parse_flat_metadata(
        open(
            os.path.join(os.path.dirname(__file__), "METADATA-implementation-marker"),
            encoding="utf-8",
        ).read()
    )
    assert {req.name for req in results.requires()} == {"yaml.clib"}


def test_a_with_extra(metadata_provider):
    info = metadata_provider("normal/a-1.0.0.METADATA")
    assert info.name == "a"
    assert info.version == pkg_resources.parse_version("0.1.0")
    assert list(info.requires("x1")) == [
        pkg_resources.Requirement.parse("b (>1); extra == 'x1'")
    ]


def test_a_with_wrong_extra(metadata_provider):
    info = metadata_provider("normal/a-1.0.0.METADATA", extras=("plop",))
    assert info.name == "a"
    assert info.version == pkg_resources.parse_version("0.1.0")
    assert not list(info.requires())


def test_pylint_python(metadata_provider):
    info = metadata_provider("real/pylint-1.9.4.METADATA", extras=())
    assert info.name == "pylint"
    assert info.version == pkg_resources.parse_version("1.9.4")

    if sys.platform == "win32":
        expected_reqs = [
            "astroid (<2.0,>=1.6)",
            "six",
            "isort (>=4.2.5)",
            "mccabe",
            'colorama; sys_platform=="win32"',
        ]
    else:
        expected_reqs = ["astroid (<2.0,>=1.6)", "six", "isort (>=4.2.5)", "mccabe"]
    assert set(info.requires()) == set(pkg_resources.parse_requirements(expected_reqs))


@pytest.mark.skipif(sys.version_info[:2] > (3, 11), reason="ed not supported on 3.12")
def test_compound(mock_targz):
    """Test one tar after another directly that have failed in the past."""
    archive = mock_targz("et_xmlfile-1.0.1")
    req_compile.metadata.metadata.extract_metadata(archive)

    archive = mock_targz("ed-1.4")
    req_compile.metadata.metadata.extract_metadata(archive)


_SOURCES = [
    ["svn-0.3.46", "svn", "0.3.46", ["python-dateutil>=2.2", "nose"]],
    ["dir-exists-1.0", "dir-exists", "1.0", ["msgpack-python"]],
    ["invalid-extra-2.1", "invalid-extra", "2.1", None],
    ["scapy-2.4.0", "scapy", "2.4.0", None],
    ["dill-0.3.0", "dill", "0.3.0", None],
    ["path-exists-2.0", "path-exists", "2.0", None],
    ["post-3.2.1-1", "post", "3.2.1-1", None],
    ["comtypes-1.1.7", "comtypes", "1.1.7", None],
    ["pkg-with-cython-1.0", "pkg-with-cython", "1.0", None],
    ["billiard-3.6.0.0", "billiard", "3.6.0.0", None],
    ["ptl-2015.11.4", "ptl", "2015.11.4", ["pytest>=2.8.1"]],
    ["reloader-1.0", "reloader", "1.0", None],
    ["PyYAML-5.1", "PyYAML", "5.1", None],
    ["pyreadline-2.1", "pyreadline", "2.1", None],
    ["termcolor-1.1.0", "termcolor", "1.1.0", None],
    ["wuc-0.5", "wuc", "0.5", None],
    ["pint-0.6", "Pint", "0.6", None],
    ["tar-utf8-1.1.0", "tar-utf8", "1.1.0", None],
    ["tar-1.0.0", "tar", "1.0.0", None],
    ["et_xmlfile-1.0.1", "et_xmlfile", "1.0.1", None],
    ["dot-slash-dir-1.0", "dot-slash-dir", "1.0", []],
    [
        "setup-cfg-0.2.0",
        "setup-cfg",
        "0.2.0",
        [
            "beautifulsoup4",
            "requests",
            'wheel ; extra=="dev"',
            'sphinx ; extra=="dev"',
            'tox ; extra=="dev"',
            'zest.releaser[recommended] ; extra=="dev"',
            'prospector[with_pyroma] ; extra=="dev"',
            'pytest ; extra=="tests"',
            'pytest-cov ; extra=="tests"',
            'pytest-mock ; extra=="tests"',
        ],
    ],
    ["cython-check-1.0", "cython-check", "1.0", ["simplejson"]],
    ["ez-setup-test-1.0", "ez-setup-test", "1.0", None],
    ["gdal-3.0.1", "GDAL", "3.0.1", []],
    ["pymc-2.3.6", "pymc", "2.3.6", []],  # Arguably this may require numpy
    ["file-iter-7.2.0", "file-iter", "7.2.0", None],
    ["psutil-5.6.2", "psutil", "5.6.2", None],
    ["pt-2.0.0", "pt", "2.0.0", None],
    ["dir-changer-0.1.1", "dir-changer", "0.1.1", ["requests"]],
    ["file-input-1.0", "file-input", "1.0", None],
    ["capital-s-1.0", "capital-s", "1.0", []],
    ["dirsep-1.0", "dirsep", "1.0", []],
    ["version-writer-1.2", "version-writer", "1.2", []],
    ["tinyrpc-1.0.4", "tinyrpc", "1.0.4", ["six"]],
    ["spec-loading-1.0", "spec-loading", "1.0", ["et_xmlfile", "jdcal"]],
]

if sys.version_info[:2] < (3, 12):
    # Uses removed configparser methods.
    _SOURCES.append(["ed-1.4", "ed", None, None])

# TODO: This should be added to the common list above.
# See https://github.com/sputt/req-compile/issues/53
if platform.system() != "Windows":
    _SOURCES.extend(
        [
            [
                "newline-req-1.0",
                "newline-req",
                "1.0",
                ["cfn_flip>=1.0.2", 'awacs>=0.8; extra == "policy"'],
            ],
        ]
    )


@pytest.mark.parametrize("archive_fixture", ["mock_targz", "mock_zip", "mock_fs"])
@pytest.mark.parametrize("directory,name,version,reqs", _SOURCES)
def test_source_dist(
    archive_fixture, directory, name, version, reqs, mock_targz, mock_zip, mocker
):
    mock_build = mocker.patch("req_compile.metadata.source._build_wheel")

    if archive_fixture == "mock_targz":
        archive = mock_targz(directory)
    elif archive_fixture == "mock_zip":
        archive = mock_zip(directory)
    else:
        archive = os.path.join(os.path.dirname(__file__), "source-packages", directory)

    metadata = req_compile.metadata.metadata.extract_metadata(archive)
    assert not mock_build.called

    if archive_fixture != "mock_fs":
        assert metadata.name == name
        if version is not None:
            assert metadata.version == pkg_resources.parse_version(version)
    if reqs is not None:
        assert set(metadata.reqs) == set(pkg_resources.parse_requirements(reqs))


def test_relative_import(mock_targz):
    archive = mock_targz("relative-import-1.0")

    metadata = req_compile.metadata.metadata.extract_metadata(archive)
    assert metadata.name == "relative-import"
    assert metadata.version == pkg_resources.parse_version("1.0")


def test_extern_import(mock_targz):
    archive = mock_targz("extern-importer-1.0")

    metadata = req_compile.metadata.metadata.extract_metadata(archive)
    assert metadata.name == "extern-importer"


def test_self_source():
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    metadata = req_compile.metadata.metadata.extract_metadata(path)
    assert metadata.name == "req-compile"
