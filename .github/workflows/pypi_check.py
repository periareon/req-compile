#!/usr/bin/env python3
"""Decide whether a wheel has anything the newest wheel on PyPI does not.

The wheels `py_wheel_library` builds are reproducible: the same sources give
the same bytes, with fixed timestamps. Two releases of the same code differ
only in METADATA, which carries the version and the changelog, in RECORD's
line for it, and in the version in the `.dist-info` directory's name. RECORD
names every other file with its hash, so comparing the two RECORDs without
those says whether the wheel carries anything PyPI's newest does not.

The sdist is not compared: it is built from the same sources by `setup.py`,
and carries version.bzl and PKG-INFO, which change with every release.

Usage: pypi_check.py <wheel>

Writes `publish=true|false` and `reason=...` to $GITHUB_OUTPUT when set, and
to stdout; the reason also goes to $GITHUB_STEP_SUMMARY when set. Exits
non-zero when PyPI cannot be read, so that nothing is decided on a guess.
"""

import json
import os
import re
import sys
import tempfile
import urllib.request
import zipfile

PROJECT = os.environ.get("PYPI_PROJECT", "req-compile")
PYPI_JSON_URL = os.environ.get("PYPI_JSON_URL", f"https://pypi.org/pypi/{PROJECT}/json")
DIST_INFO = re.compile(r"^[^/]+\.dist-info/")
VERSIONED = {"METADATA", "RECORD"}


def emit(publish: bool, reason: str) -> None:
    lines = [f"publish={'true' if publish else 'false'}", f"reason={reason}"]
    print("\n".join(lines))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write("\n".join(lines) + "\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as out:
            out.write(f"PyPI: {reason}\n")


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": f"{PROJECT} release workflow"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        return response.read()


def record(wheel: str) -> dict:
    """Path -> RECORD line, without the files that carry the version."""
    with zipfile.ZipFile(wheel) as archive:
        name = next(n for n in archive.namelist() if DIST_INFO.match(n) and n.endswith("/RECORD"))
        lines = archive.read(name).decode("utf-8").splitlines()
    entries = {}
    for line in lines:
        path = line.split(",")[0]
        if DIST_INFO.match(path):
            if path.rsplit("/", 1)[1] in VERSIONED:
                continue
            path = DIST_INFO.sub("DIST-INFO/", path)
            line = DIST_INFO.sub("DIST-INFO/", line)
        entries[path] = line
    return entries


def main() -> int:
    wheel = sys.argv[1]
    try:
        releases = json.loads(fetch(PYPI_JSON_URL))["releases"]
    except Exception as error:  # pylint: disable=broad-exception-caught
        print(f"ERROR: could not read {PYPI_JSON_URL}: {error}; not deciding whether to publish without it", file=sys.stderr)
        return 1
    published = sorted(
        (max(f["upload_time"] for f in files), version, files)
        for version, files in releases.items()
        if files and not all(f.get("yanked") for f in files)
    )
    if not published:
        emit(True, "PyPI has no release yet, so the distributions are published.")
        return 0
    _, latest, files = published[-1]
    wheels = [f["url"] for f in files if f["packagetype"] == "bdist_wheel"]
    if not wheels:
        emit(True, f"{latest}, the newest release on PyPI, has no wheel to compare with, so the distributions are published.")
        return 0
    with tempfile.TemporaryDirectory() as scratch:
        theirs_path = os.path.join(scratch, "pypi.whl")
        try:
            with open(theirs_path, "wb") as out:
                out.write(fetch(wheels[0]))
        except Exception as error:  # pylint: disable=broad-exception-caught
            print(f"ERROR: could not download {wheels[0]}: {error}; not deciding whether to publish without it", file=sys.stderr)
            return 1
        theirs = record(theirs_path)
    ours = record(wheel)
    changed = sorted(path for path in set(ours) | set(theirs) if ours.get(path) != theirs.get(path))
    if changed:
        emit(True, f"the wheel differs from {latest}, the newest release on PyPI, so the distributions are published. Changed: {' '.join(changed)}")
    else:
        emit(False, f"the wheel has the same files as {latest}, the newest release on PyPI, so the distributions are not published.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
