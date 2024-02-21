import pytest

from req_compile.utils import has_prerelease, parse_requirement


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
