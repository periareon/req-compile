import pkg_resources
import pytest

from qer.versions import is_possible, _offset_minor_version

parse_req = pkg_resources.Requirement.parse


@pytest.mark.parametrize('version, offset, result', [
    ('1', 1, '1.0.1'),
    ('1', -1, '0.999999999.999999999'),
    ('1.4.0', -1, '1.3.999999999'),
    ('1.4.0', 1, '1.4.1'),
    ('1.4.4.22', 1, '1.4.5.22'),
])
def test_offset_version(version, offset, result):
    version = pkg_resources.parse_version(version)
    assert _offset_minor_version(version, offset) == pkg_resources.parse_version(result)


def test_two_equals():
    assert not is_possible(parse_req('thing==1,==2'))


def test_greater_less():
    assert not is_possible(parse_req('thing>1.12,<1'))


def test_greater_equal():
    assert not is_possible(parse_req('thing>1.12,==1.0.2'))


def test_equals_not_equals():
    assert not is_possible(parse_req('thing==1,!=1'))


def test_no_constraints():
    assert is_possible(parse_req('thing'))


def test_two_greater():
    assert is_possible(parse_req('thing>1,>2,<3'))


def test_two_greater_equals():
    assert is_possible(parse_req('thing>1,>=2,==2'))


def test_gre_lte():
    assert is_possible(parse_req('thing>=1,<=1'))


def test_gre_lte_equals():
    assert is_possible(parse_req('thing>=1,<=1,==1'))


def test_not_equals():
    assert is_possible(parse_req('thing!=1'))
    assert is_possible(parse_req('thing!=1,!=2,!=3'))


def test_gr():
    assert is_possible(parse_req('thing>1'))


def test_lt():
    assert is_possible(parse_req('thing<1'))
