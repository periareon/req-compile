import contextlib
import logging
import os

import pytest

import req_compile.metadata.extractor
from req_compile.metadata.extractor import TarExtractor


@contextlib.contextmanager
def temp_cwd(new_cwd):
    old_cwd = os.getcwd()
    try:
        os.chdir(new_cwd)
        yield new_cwd
    finally:
        os.chdir(old_cwd)


@pytest.mark.parametrize("archive_fixture", ["mock_targz", "mock_zip", "mock_zip"])
def test_extractor(archive_fixture, mock_targz, mock_zip):
    directory = "comtypes-1.1.7"
    if archive_fixture == "mock_targz":
        archive = mock_targz(directory)
    elif archive_fixture == "mock_zip":
        archive = mock_zip(directory)
    else:
        archive = os.path.abspath(os.path.join("source-packages", directory))

    if archive_fixture == "mock_targz":
        extractor = req_compile.metadata.extractor.TarExtractor("gz", archive)
        prefix = directory + "/"
    elif archive_fixture == "mock_zip":
        extractor = req_compile.metadata.extractor.ZipExtractor(archive)
        prefix = directory + "/"
    else:
        extractor = req_compile.metadata.extractor.NonExtractor(archive)
        prefix = ""

    with contextlib.closing(extractor):
        all_names = set(extractor.names())
        assert all_names == {
            prefix + "README",
            prefix + "setup.py",
            prefix + "comtypes/__init__.py",
            prefix + "test/setup.py",
        }

        prefix = extractor.fake_root + os.sep + prefix

        assert extractor.contents(prefix + "README") == "README CONTENTS"
        with extractor.open(prefix + "README") as handle:
            assert handle.read(2) == "RE"
        assert extractor.contents(prefix + "README") == "README CONTENTS"
        assert extractor.exists(prefix + "test")
        assert extractor.exists(prefix + "test/setup.py")
        assert not extractor.exists(prefix + "test/setup2.py")


def test_wrapped_encoding(mock_targz, tmp_path):
    directory = "comtypes-1.1.7"
    archive: TarExtractor = TarExtractor("gz", mock_targz(directory))

    root = str(tmp_path)
    archive.fake_root = root
    with temp_cwd(root):
        with archive.open("comtypes-1.1.7/setup.py", "rb") as bin_file:
            assert isinstance(bin_file.read(1), bytes)
        with archive.open("comtypes-1.1.7/setup.py", "r") as ascii_file:
            assert isinstance(ascii_file.read(1), str)
        with archive.open(
            "comtypes-1.1.7/setup.py", "r", encoding="utf-8"
        ) as utf8_file:
            assert isinstance(utf8_file.read(1), str)
