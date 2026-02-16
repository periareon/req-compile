import functools
import sys

import pytest

from req_compile.errors import MetadataError
from req_compile.metadata.dist_info import _fetch_from_wheel
from req_compile.metadata.extractor import TarExtractor, ZipExtractor
from req_compile.metadata.source import _fetch_from_source


def test_source_junk_tar_file(tmp_path):
    """Junk tar files should raise metadata errors so that these distributions won't be used."""
    junk_tar = tmp_path / "junk.tar.gz"
    junk_tar.write_bytes(b"junk")

    with pytest.raises(MetadataError):
        _fetch_from_source(junk_tar, functools.partial(TarExtractor, "gz"))


def test_source_junk_zip(tmp_path):
    """Junk zip dists also should fail."""
    junk_zip = tmp_path / "junk.zip"
    junk_zip.write_bytes(b"junk")

    with pytest.raises(MetadataError):
        _fetch_from_source(junk_zip, ZipExtractor)


def test_junk_wheel(tmp_path):
    """Extracting metadata should fail if the wheel is bad."""
    junk_whl = tmp_path / "junk.whl"
    junk_whl.write_bytes(b"junk")

    assert _fetch_from_wheel(junk_whl) is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
