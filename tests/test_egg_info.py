"""Tests for EggInfoDistInfo and egg-info requires.txt parsing."""

import textwrap

import packaging.requirements
import pytest
from packaging.requirements import InvalidRequirement

from req_compile.containers import EggInfoDistInfo, _format_req_str, _parse_requires_txt


def test_format_req_str_simple():
    req = packaging.requirements.Requirement("requests>=2.0")
    assert _format_req_str(req) == "requests>=2.0"


def test_format_req_str_with_extras():
    req = packaging.requirements.Requirement("requests[security,socks]>=2.0")
    result = _format_req_str(req)
    assert "requests" in result
    assert "security" in result
    assert "socks" in result
    assert ">=2.0" in result


def test_format_req_str_url():
    req = packaging.requirements.Requirement(
        "mypackage @ https://example.com/mypackage-1.0.tar.gz"
    )
    result = _format_req_str(req)
    assert "mypackage" in result
    assert "@ https://example.com/mypackage-1.0.tar.gz" in result


def test_format_req_str_url_with_extras():
    req = packaging.requirements.Requirement(
        "mypackage[extra1] @ https://example.com/pkg.tar.gz"
    )
    result = _format_req_str(req)
    assert "[extra1]" in result
    assert "@ https://example.com/pkg.tar.gz" in result


def test_format_req_str_no_specifier():
    req = packaging.requirements.Requirement("requests")
    assert _format_req_str(req) == "requests"


def test_parse_requires_txt_simple(tmp_path):
    requires = tmp_path / "requires.txt"
    requires.write_text("requests>=2.0\nflask>=1.0\n")
    reqs = _parse_requires_txt(str(requires))
    assert len(reqs) == 2
    assert reqs[0].name == "requests"
    assert reqs[1].name == "flask"


def test_parse_requires_txt_extra_section(tmp_path):
    requires = tmp_path / "requires.txt"
    requires.write_text(
        textwrap.dedent(
            """\
        requests>=2.0
        [security]
        pyOpenSSL>=0.14
        cryptography>=1.3.4
    """
        )
    )
    reqs = _parse_requires_txt(str(requires))
    assert len(reqs) == 3
    assert reqs[0].name == "requests"
    assert reqs[0].marker is None
    assert reqs[1].name == "pyOpenSSL"
    assert 'extra == "security"' in str(reqs[1].marker)
    assert reqs[2].name == "cryptography"
    assert 'extra == "security"' in str(reqs[2].marker)


def test_parse_requires_txt_extra_with_marker(tmp_path):
    requires = tmp_path / "requires.txt"
    requires.write_text(
        textwrap.dedent(
            """\
        [security:python_version<"3.0"]
        pyOpenSSL>=0.14
    """
        )
    )
    reqs = _parse_requires_txt(str(requires))
    assert len(reqs) == 1
    assert reqs[0].name == "pyOpenSSL"
    marker_str = str(reqs[0].marker)
    assert 'extra == "security"' in marker_str
    assert 'python_version < "3.0"' in marker_str


def test_parse_requires_txt_marker_only_section(tmp_path):
    requires = tmp_path / "requires.txt"
    requires.write_text(
        textwrap.dedent(
            """\
        [:python_version<"3.0"]
        futures>=2.0
    """
        )
    )
    reqs = _parse_requires_txt(str(requires))
    assert len(reqs) == 1
    assert reqs[0].name == "futures"
    assert 'python_version < "3.0"' in str(reqs[0].marker)


def test_parse_requires_txt_empty_lines(tmp_path):
    requires = tmp_path / "requires.txt"
    requires.write_text("requests>=2.0\n\n\nflask>=1.0\n")
    reqs = _parse_requires_txt(str(requires))
    assert len(reqs) == 2


def test_parse_requires_txt_invalid_lines(tmp_path):
    requires = tmp_path / "requires.txt"
    requires.write_text("requests>=2.0\n!!!invalid\nflask>=1.0\n")
    with pytest.raises(InvalidRequirement, match=r"!!!invalid"):
        _parse_requires_txt(str(requires))


def test_egg_info_from_dir(tmp_path):
    egg_dir = tmp_path / "mypackage.egg-info"
    egg_dir.mkdir()
    (egg_dir / "PKG-INFO").write_text(
        textwrap.dedent(
            """\
        Metadata-Version: 1.0
        Name: mypackage
        Version: 1.2.3
    """
        )
    )
    (egg_dir / "requires.txt").write_text("requests>=2.0\nflask>=1.0\n")

    info = EggInfoDistInfo(str(egg_dir))
    assert info.name == "mypackage"
    assert str(info.version) == "1.2.3"
    assert len(info.reqs) == 2


def test_egg_info_missing_pkg_info(tmp_path):
    egg_dir = tmp_path / "mypackage.egg-info"
    egg_dir.mkdir()
    (egg_dir / "requires.txt").write_text("requests>=2.0\n")

    info = EggInfoDistInfo(str(egg_dir), project_name="fallback")
    assert info.name == "fallback"
    assert info.version is None


def test_egg_info_missing_requires_txt(tmp_path):
    egg_dir = tmp_path / "mypackage.egg-info"
    egg_dir.mkdir()
    (egg_dir / "PKG-INFO").write_text(
        textwrap.dedent(
            """\
        Metadata-Version: 1.0
        Name: mypackage
        Version: 0.1.0
    """
        )
    )

    info = EggInfoDistInfo(str(egg_dir))
    assert info.name == "mypackage"
    assert len(info.reqs) == 0
