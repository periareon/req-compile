import os

from req_compile.metadata import extract_metadata
from req_compile.utils import parse_requirements, parse_version


def test_no_setup_py():
    """Test that a pyproject build of a setuptools project can be built when
    the project does not have a setup.py."""
    result = extract_metadata(os.path.join(os.path.dirname(__file__), "no-setup-py"))
    assert result.name == "mypackage"
    assert result.version == parse_version("0.0.1")
    assert set(result.reqs) == set(
        parse_requirements(
            [
                "requests",
                "importlib; python_version == '2.6'",
            ]
        )
    )
