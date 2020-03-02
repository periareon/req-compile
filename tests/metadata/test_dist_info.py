import os

from req_compile.metadata.dist_info import _find_dist_info_metadata


def test_wheel_with_vendored():
    """Verify that a wheel that contains vendored dist-info directories uses the correct one"""
    namelist_raw = open(
        os.path.join(os.path.dirname(__file__), "pex-listing.txt")
    ).readlines()
    namelist = [name.strip() for name in namelist_raw]

    assert _find_dist_info_metadata("pex", namelist) == "pex-2.1.3.dist-info/METADATA"
    assert (
        _find_dist_info_metadata("pex", list(reversed(namelist)))
        == "pex-2.1.3.dist-info/METADATA"
    )


def test_normal_wheel():
    assert (
        _find_dist_info_metadata(
            "normal", ["normal/__init__.py", "metadata", "normal.dist-info/METADATA"]
        )
        == "normal.dist-info/METADATA"
    )


def test_best_effort_match():
    """If the wheel file name is wrong the correct project info can still be found"""
    assert (
        _find_dist_info_metadata(
            "bad", ["normal/__init__.py", "normal.dist-info/METADATA"]
        )
        == "normal.dist-info/METADATA"
    )


def test_not_found():
    """Bad zips won't have any metadata"""
    assert _find_dist_info_metadata("bad", ["totally", "wrong", "files"]) is None
