"""Integration tests."""
import os
import subprocess
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))


def test_source_candidates():
    """Verify the current directory shows a candidate."""
    result = subprocess.run(
        [sys.executable, "-m", "req_compile.candidates", "--pre"],
        encoding="utf-8",
        capture_output=True,
        cwd=ROOT_DIR,
    )
    assert "req-compile" in result.stdout
    assert result.stdout.count("\n") == 1
    assert "Found 1 compatible" in result.stderr


def test_no_candidates(tmp_path):
    """Verify finding no candidates works correctly."""
    env_copy = os.environ.copy()
    env_copy["PYTHONPATH"] = ROOT_DIR

    result = subprocess.run(
        [sys.executable, "-m", "req_compile.candidates", "--pre"],
        encoding="utf-8",
        capture_output=True,
        env=env_copy,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert "0" in result.stderr, result.stderr


def test_compile_req_compile(tmp_path):
    """Test compiling this project from source."""
    result = subprocess.run(
        [sys.executable, "-m", "req_compile", ".", "--wheel-dir", str(tmp_path)],
        encoding="utf-8",
        capture_output=True,
        cwd=ROOT_DIR,
    )
    assert result.returncode == 0
    assert "req-compile" in result.stdout
    assert "toml" in result.stdout
    assert result.stderr == ""

    # Ensure that setup requires are included.
    all_items = {path.name.split("-", 1)[0] for path in tmp_path.iterdir()}
    assert "setuptools" in all_items
