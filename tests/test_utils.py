import pytest

from req_compile.utils import (
    has_prerelease,
    parse_requirement,
    parse_requirements,
    req_iter_from_lines,
)


@pytest.mark.parametrize(
    "expression,result",
    [
        ("thing>=2.3.1b1", True),
        ("thing==2.*", False),
        ("thing==1!2.2.*", False),
        ("thing==2pre3", True),
        ("thing==4a4", True),
    ],
)
def test_has_prerelease(expression, result):
    """Verify requirement expressions can be scanned for prerelease."""
    assert has_prerelease(parse_requirement(expression)) == result


class TestInlineCommentStripping:
    """Test that inline comments are stripped from requirement lines."""

    def test_parse_requirements_strips_inline_comment(self):
        reqs = list(parse_requirements(["setuptools<82  # Required for pkg_resources"]))
        assert len(reqs) == 1
        assert reqs[0].name == "setuptools"
        assert str(reqs[0].specifier) == "<82"

    def test_parse_requirements_preserves_markers(self):
        reqs = list(parse_requirements(['foo>=1.0; python_version>="3.9"']))
        assert len(reqs) == 1
        assert reqs[0].name == "foo"
        assert reqs[0].marker is not None

    def test_parse_requirements_comment_only_after_strip(self):
        reqs = list(parse_requirements([" # just a comment"]))
        assert len(reqs) == 0

    def test_req_iter_from_lines_strips_inline_comment(self):
        lines = ["setuptools<82  # a pin\n", "requests>=2.0  # needed\n"]
        params = []
        reqs = list(req_iter_from_lines(lines, params))
        assert len(reqs) == 2
        assert reqs[0].name == "setuptools"
        assert str(reqs[0].specifier) == "<82"
        assert reqs[1].name == "requests"

    def test_req_iter_from_lines_hash_in_url_preserved(self):
        """Ensure # in --hash flags are handled by existing code path."""
        lines = ["requests==2.28.0 --hash=sha256:abc123\n"]
        params = []
        reqs = list(req_iter_from_lines(lines, params))
        assert len(reqs) == 1
        assert reqs[0].name == "requests"
        assert str(reqs[0].specifier) == "==2.28.0"
