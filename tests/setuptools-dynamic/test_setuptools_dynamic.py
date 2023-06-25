import os

from req_compile.metadata import extract_metadata
from req_compile.utils import parse_requirements, parse_version


def test_setuptools_dynamic():
    """Test that setuptools that reads [project] works."""
    result = extract_metadata(os.path.dirname(__file__))
    assert result.name == "setuptools-dynamic"
    assert result.version == parse_version("1.0.0")
    assert set(result.reqs) == set(
        parse_requirements(
            [
                "flask",
            ]
        )
    )
