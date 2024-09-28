import pkg_resources
import pytest

from req_compile.versions import _offset_minor_version, is_possible

parse_req = pkg_resources.Requirement.parse


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
    version = pkg_resources.parse_version(version)
    assert _offset_minor_version(version, offset) == pkg_resources.parse_version(result)


def test_two_equals() -> None:
    assert not is_possible(parse_req("thing==1,==2"))


def test_greater_less() -> None:
    assert not is_possible(parse_req("thing>1.12,<1"))


def test_greater_equal() -> None:
    assert not is_possible(parse_req("thing>1.12,==1.0.2"))


def test_equals_not_equals() -> None:
    assert not is_possible(parse_req("thing==1,!=1"))


def test_dev_version() -> None:
    assert not is_possible(parse_req("thing<1.6,<2.0dev,>=1.5,>=1.6.0"))


def test_beta_version() -> None:
    assert is_possible(parse_req("thing<20b0"))


def test_no_constraints() -> None:
    assert is_possible(parse_req("thing"))


def test_edge_equals() -> None:
    assert pkg_resources.parse_version("2.1.1") in parse_req("thing>2.1")
    assert is_possible(parse_req("thing==2.1.1,>2.1"))

    assert pkg_resources.parse_version("2.1.0") not in parse_req("thing>2.1")
    assert not is_possible(parse_req("thing==2.1.0,>2.1"))


def test_two_greater() -> None:
    assert is_possible(parse_req("thing>1,>2,<3"))


def test_two_greater_equals() -> None:
    assert is_possible(parse_req("thing>1,>=2,==2"))


def test_gre_lte() -> None:
    assert is_possible(parse_req("thing>=1,<=1"))


def test_gre_lte_equals() -> None:
    assert is_possible(parse_req("thing>=1,<=1,==1"))


def test_not_equals() -> None:
    assert is_possible(parse_req("thing!=1"))
    assert is_possible(parse_req("thing!=1,!=2,!=3"))


def test_gr() -> None:
    assert is_possible(parse_req("thing>1"))


def test_lt() -> None:
    assert is_possible(parse_req("thing<1"))


def test_wildcard_possible() -> None:
    assert is_possible(parse_req("thing>1,==2.*,<3"))
    assert is_possible(parse_req("thing>1,==2.*,==2.1.2,<3"))

    # Show that with this wildcard expression, a version can satisfy it.
    wildcard_req = parse_req("thing>2.1.0,==2.1.*")
    assert pkg_resources.parse_version("2.1.2") in wildcard_req
    # Sanity check one that does not satisfy it.
    assert pkg_resources.parse_version("2.2.0") not in wildcard_req
    # Run the is possible check.
    assert is_possible(wildcard_req)


def test_wildcard_not_possible() -> None:
    assert not is_possible(parse_req("thing<1,==2.*"))
    assert not is_possible(parse_req("thing>2.1,==2.0.*"))


def test_wildcard_not_equal_possible() -> None:
    wildcard_req = parse_req("thing>2.1.0,!=2.1.*")
    assert pkg_resources.parse_version("3.0") in wildcard_req
    assert pkg_resources.parse_version("2.1.1") not in wildcard_req

    assert is_possible(wildcard_req)


def test_wildcard_subrange() -> None:
    wildcard_req = parse_req("thing==2.*,!=2.1.*")
    assert pkg_resources.parse_version("2.2") in wildcard_req
    assert pkg_resources.parse_version("2.1.1") not in wildcard_req

    assert is_possible(wildcard_req)

    wildcard_req = parse_req("thing==2.1.*,!=2.*")
    assert pkg_resources.parse_version("2.1.1") not in wildcard_req
    assert not is_possible(wildcard_req)


def test_wildcard_double_not() -> None:
    wildcard_req = parse_req("thing!=2.*,!=3.*,>1")
    assert pkg_resources.parse_version("4") in wildcard_req
    assert pkg_resources.parse_version("2") not in wildcard_req
    assert pkg_resources.parse_version("3") not in wildcard_req

    assert is_possible(wildcard_req)
