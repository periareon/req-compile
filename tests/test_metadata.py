import os
import sys

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
    assert list(info.requires()) == []


def test_parse_flat_metadata_extra_space():
    results = req_compile.metadata.dist_info._parse_flat_metadata(
        open(os.path.join(os.path.dirname(__file__), "METADATA-extra-space")).read()
    )
    assert results.requires() == [pkg_resources.Requirement.parse("django")]


def test_parse_flat_metadata_two_names():
    results = req_compile.metadata.dist_info._parse_flat_metadata(
        open(os.path.join(os.path.dirname(__file__), "METADATA-two-names")).read()
    )
    assert results.name == "fabio"


def test_parse_flat_metadata_bizarre_extra():
    results = req_compile.metadata.dist_info._parse_flat_metadata(
        open(os.path.join(os.path.dirname(__file__), "METADATA-bizarre-extra")).read()
    )
    assert results.name == "setuptools"
    assert results.requires() == []
    assert results.requires(extra="ssl:sys_platform=='win32'")[0].name == "wincertstore"


def test_parse_flat_metadata_complex_marker():
    results = req_compile.metadata.dist_info._parse_flat_metadata(
        open(
            os.path.join(os.path.dirname(__file__), "METADATA-implementation-marker")
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
    assert list(info.requires()) == []


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


@pytest.mark.parametrize(
    "filename,result_name,result_version",
    [
        ["post-2.3.1-2.tar.gz", "post", "2.3.1-2"],
        ["pytest-ui-0.3b0.linux-x86_64.tar.gz", "pytest-ui", "0.3beta0"],
        ["backports-thing-1.0.1.tar.gz", "backports-thing", "1.0.1"],
        ["backports-thing-1.0.1.tar.gz", "backports-thing", "1.0.1"],
        ["project-v1.0.tar.gz", "project", "1.0"],
        ["pyvmomi-5.5.0.2014.1.1.tar.gz", "pyvmomi", "5.5.0.2014.1.1"],
        ["pyvmomi-5.5.0-2014.1.1.tar.gz", "pyvmomi", "5.5.0-2014.1.1"],
        ["python-project-3-0.0.1.tar.gz", "python-project-3", "0.0.1"],
        ["python-project-v2-0.1.1.tar.gz", "python-project-v2", "0.1.1"],
        ["divisor-1.0.0s-1.0.0.zip", "divisor-1.0.0s", "1.0.0"],
        [
            "django-1.6-fine-uploader-0.2.0.3.tar.gz",
            "django-1.6-fine-uploader",
            "0.2.0.3",
        ],
        ["selenium-2.0-dev-9429.tar.gz", "selenium", "2.0-dev-9429"],
        ["django-ajax-forms_0.3.1.tar.gz", "django-ajax-forms", "0.3.1"],
    ],
)
def test_parse_source_filename(filename, result_name, result_version):
    result = req_compile.filename.parse_source_filename(filename)
    assert result == (result_name, pkg_resources.parse_version(result_version))


def test_compound(mock_targz):
    """Test one tar after another directly that have failed in the passed"""
    archive = mock_targz("et_xmlfile-1.0.1")
    req_compile.metadata.metadata.extract_metadata(archive)

    archive = mock_targz("ed-1.4")
    req_compile.metadata.metadata.extract_metadata(archive)


sources = [
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
    ["ed-1.4", "ed", None, None],
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
    [
        "newline-req-1.0",
        "newline-req",
        "1.0",
        ["cfn_flip>=1.0.2", 'awacs>=0.8; extra == "policy"'],
    ],
    ["version-writer-1.2", "version-writer", "1.2", []],
    ["tinyrpc-1.0.4", "tinyrpc", "1.0.4", ["six"]],
]
sources.append(["spec-loading-1.0", "spec-loading", "1.0", ["et_xmlfile", "jdcal"]])


@pytest.mark.parametrize("archive_fixture", ["mock_targz", "mock_zip", "mock_fs"])
@pytest.mark.parametrize("directory,name,version,reqs", sources)
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


def test_self_source():
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    metadata = req_compile.metadata.metadata.extract_metadata(path)
    assert metadata.name == "req-compile"
