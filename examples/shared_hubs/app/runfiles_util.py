"""Helpers for inspecting the runfiles of a test."""

import os
from pathlib import Path


def runfiles_repositories() -> set[str]:
    """The names of the repositories present in the runfiles of this test."""
    manifest = os.environ.get("RUNFILES_MANIFEST_FILE")
    if manifest and Path(manifest).exists():
        entries = [
            line.split(" ", 1)[0]
            for line in Path(manifest).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return {entry.split("/", 1)[0] for entry in entries}
    return {path.name for path in Path(os.environ["TEST_SRCDIR"]).iterdir()}
