"""Check that hubs pinning the same wheel share its repository."""

import os
import unittest
from pathlib import Path

import click  # pylint: disable=import-error
import requests  # pylint: disable=import-error
from shared_hubs_lib import locations  # pylint: disable=import-error


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


class SharedWheelsTest(unittest.TestCase):
    def test_single_repository_per_wheel(self) -> None:
        repositories = runfiles_repositories()
        for package in ("click_8_1_7_", "requests_2_32_3_"):
            matches = sorted(repo for repo in repositories if package in repo)
            self.assertEqual(
                len(matches),
                1,
                f"Expected one repository for {package}, found {matches}",
            )

    def test_same_files_in_both_hubs(self) -> None:
        lib_locations = locations()
        self.assertEqual(
            Path(click.__file__).resolve(), Path(lib_locations["click"]).resolve()
        )
        self.assertEqual(
            Path(requests.__file__).resolve(),
            Path(lib_locations["requests"]).resolve(),
        )
        self.assertRegex(
            str(Path(click.__file__).as_posix()),
            r"click_8_1_7_[0-9a-f]{8}(_[0-9a-f]{8})?/site-packages/click/",
        )


if __name__ == "__main__":
    unittest.main()
