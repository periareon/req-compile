import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from req_compile.versions import _offset_minor_version, is_possible



@pytest.mark.parametrize(
    "version, offset, result",
    [
        ("1", 1, "1.0.1"),
        ("1", -1, "0.999999999.999999999"),
        ("1.4.0", -1, "1.3.999999999"),
        ("1.4.0", 1, "1.4.1"),
        ("1.4.4.22", 1, "1.4.5.22"),
        ("1.4.4b20", 1, "1.4.5"),
    ],
)
def test_offset_version(version, offset, result):
    version = Version(version)
    assert _offset_minor_version(version, offset) == Version(result)


def test_two_equals() -> None:
    assert not is_possible(Requirement("thing==1,==2"))


def test_greater_less() -> None:
    assert not is_possible(Requirement("thing>1.12,<1"))


def test_greater_equal() -> None:
    assert not is_possible(Requirement("thing>1.12,==1.0.2"))


def test_equals_not_equals() -> None:
    assert not is_possible(Requirement("thing==1,!=1"))


def test_dev_version() -> None:
    assert not is_possible(Requirement("thing<1.6,<2.0dev,>=1.5,>=1.6.0"))


def test_beta_version() -> None:
    assert is_possible(Requirement("thing<20b0"))


def test_no_constraints() -> None:
    assert is_possible(Requirement("thing"))


def test_edge_equals() -> None:
    assert Requirement("thing>2.1").specifier.contains("2.1.1", prereleases=True)
    assert is_possible(Requirement("thing==2.1.1,>2.1"))

    assert not Requirement("thing>2.1").specifier.contains("2.1.0", prereleases=True)
    assert not is_possible(Requirement("thing==2.1.0,>2.1"))


def test_two_greater() -> None:
    assert is_possible(Requirement("thing>1,>2,<3"))


def test_two_greater_equals() -> None:
    assert is_possible(Requirement("thing>1,>=2,==2"))


def test_gre_lte() -> None:
    assert is_possible(Requirement("thing>=1,<=1"))


def test_gre_lte_equals() -> None:
    assert is_possible(Requirement("thing>=1,<=1,==1"))


def test_not_equals() -> None:
    assert is_possible(Requirement("thing!=1"))
    assert is_possible(Requirement("thing!=1,!=2,!=3"))


def test_gr() -> None:
    assert is_possible(Requirement("thing>1"))


def test_lt() -> None:
    assert is_possible(Requirement("thing<1"))


def test_wildcard_possible() -> None:
    assert is_possible(Requirement("thing>1,==2.*,<3"))
    assert is_possible(Requirement("thing>1,==2.*,==2.1.2,<3"))

    # Show that with this wildcard expression, a version can satisfy it.
    wildcard_req = Requirement("thing>2.1.0,==2.1.*")
    assert wildcard_req.specifier.contains("2.1.2", prereleases=True)
    # Sanity check one that does not satisfy it.
    assert not wildcard_req.specifier.contains("2.2.0", prereleases=True)
    # Run the is possible check.
    assert is_possible(wildcard_req)


def test_wildcard_not_possible() -> None:
    assert not is_possible(Requirement("thing<1,==2.*"))
    assert not is_possible(Requirement("thing>2.1,==2.0.*"))


def test_wildcard_not_equal_possible() -> None:
    wildcard_req = Requirement("thing>2.1.0,!=2.1.*")
    assert wildcard_req.specifier.contains("3.0", prereleases=True)
    assert not wildcard_req.specifier.contains("2.1.1", prereleases=True)

    assert is_possible(wildcard_req)


def test_wildcard_subrange() -> None:
    wildcard_req = Requirement("thing==2.*,!=2.1.*")
    assert wildcard_req.specifier.contains("2.2", prereleases=True)
    assert not wildcard_req.specifier.contains("2.1.1", prereleases=True)

    assert is_possible(wildcard_req)

    wildcard_req = Requirement("thing==2.1.*,!=2.*")
    assert not wildcard_req.specifier.contains("2.1.1", prereleases=True)
    assert not is_possible(wildcard_req)


def test_wildcard_double_not() -> None:
    wildcard_req = Requirement("thing!=2.*,!=3.*,>1")
    assert wildcard_req.specifier.contains("4", prereleases=True)
    assert not wildcard_req.specifier.contains("2", prereleases=True)
    assert not wildcard_req.specifier.contains("3", prereleases=True)

    assert is_possible(wildcard_req)
