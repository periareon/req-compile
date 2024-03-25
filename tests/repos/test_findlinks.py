import os
import subprocess
import sys

from req_compile.repos.findlinks import FindLinksRepository


def test_find_links(tmpdir):
    """Verify that a wheel for req-compile can be discovered properly"""
    wheeldir = str(tmpdir.mkdir("wheeldir"))

    source_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    subprocess.run(
        [sys.executable, "setup.py", "bdist_wheel", "--dist-dir", wheeldir],
        cwd=source_dir,
        check=True,
    )

    repo = FindLinksRepository(wheeldir)
    candidates = list(repo.get_candidates(None))
    assert len(candidates) == 1
    assert candidates[0].name == "req_compile"


def test_relative_to_repr(tmpdir):
    (tmpdir / "wheeldir").mkdir()
    assert str(FindLinksRepository(tmpdir)) == f"--find-links {tmpdir}"

    assert (
        str(FindLinksRepository(tmpdir / "wheeldir", relative_to=tmpdir))
        == "--find-links wheeldir"
    )

    assert (
        str(FindLinksRepository(tmpdir / "wheeldir", relative_to=tmpdir / "3rdparty"))
        == "--find-links ../wheeldir"
    )
