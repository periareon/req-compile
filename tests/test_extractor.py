import contextlib
import logging
import os

import pytest

import req_compile.metadata.extractor


@contextlib.contextmanager
def temp_cwd(new_cwd):
    old_cwd = os.getcwd()
    try:
        os.chdir(new_cwd)
        yield new_cwd
    finally:
        os.chdir(old_cwd)


@pytest.mark.parametrize("archive_fixture", ["mock_targz", "mock_zip", "mock_zip"])
def test_extractor(archive_fixture, tmpdir, mock_targz, mock_zip):
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
