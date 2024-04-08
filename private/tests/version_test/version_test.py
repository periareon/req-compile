"""A suite of tests ensuring version strings are all in sync."""

import re
import unittest
from pathlib import Path

from rules_python.python.runfiles import Runfiles  # pylint: disable=import-error


def rlocation(runfiles: Runfiles, rlocationpath: str) -> Path:
    """Look up a runfile and ensure the file exists

    Args:
        runfiles: The runfiles object
        rlocationpath: The runfile key

    Returns:
        The requested runifle.
    """
    runfile = runfiles.Rlocation(rlocationpath)
    if not runfile:
        raise FileNotFoundError(f"Failed to find runfile: {rlocationpath}")
    path = Path(runfile)
    if not path.exists():
        raise FileNotFoundError(f"Runfile does not exist: ({rlocationpath}) {path}")
    return path


class VersionTest(unittest.TestCase):
    def test_versions(self):
        runfiles = Runfiles.Create()
        if not runfiles:
            raise EnvironmentError("Failed to locate runfiles.")

        version_bzl = rlocation(runfiles, "rules_req_compile/version.bzl")
        bzl_version = re.findall(
            r'VERSION = "([\w\d\.]+)"',
            version_bzl.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        assert bzl_version, f"Failed to parse version from {version_bzl}"

        module_bazel = rlocation(runfiles, "rules_req_compile/MODULE.bazel")
        module_version = re.findall(
            r'module\(\n\s+name = "rules_req_compile",\n\s+version = "([\d\w\.]+)",\n\)',
            module_bazel.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        assert module_version, f"Failed to parse version from {module_bazel}"

        assert (
            bzl_version[0] == module_version[0]
        ), f"{bzl_version[0]} == {module_version[0]}"


if __name__ == "__main__":
    unittest.main()
