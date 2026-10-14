"""Test cross platform consumers of req-compile repository rules."""

import os
import re
import unittest
import zipfile
from pathlib import Path

from python.runfiles import Runfiles  # pylint: disable=import-error


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


def wheel_repositories(lock: Path) -> dict[str, str]:
    """Compute the name of the wheel repository of every package in a lock file.

    Wheel repositories are named `{package}_{version}_{sha256[:8]}`, so two locks
    pinning the same file share a repository.
    """
    repos = {}
    name = ""
    version = ""
    for line in lock.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if "==" in text and not text.startswith("#"):
            name, _, version = text.rstrip(" \\").partition("==")
        elif text.startswith("--hash=sha256:") and name:
            sanitized = name.replace("-", "_").replace(".", "_").lower()
            repos[sanitized] = "{}_{}_{}".format(
                sanitized,
                re.sub(r"[^0-9A-Za-z]", "_", version),
                text[len("--hash=sha256:") :][:8],
            )
            name = ""
    return repos


class CrossPlatformZipTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.RUNFILES = Runfiles.Create()
        if not cls.RUNFILES:
            raise EnvironmentError("Failed to locate runfiles.")
        cls.REPOS = {
            platform: wheel_repositories(
                rlocation(cls.RUNFILES, os.environ[f"REQUIREMENTS_{platform.upper()}"])
            )
            for platform in ("linux", "macos", "windows")
        }

    def python_zip_file_tester(
        self, rlocationpath: str, expected: list[str], illegal_prefixes: tuple[str, ...]
    ) -> None:
        """Test the zip file for the requested platform.

        Args:
            rlocationpath: The runfiles key for the zip file to test.
            expected: A list of paths expected to be in the zip.
            illegal_prefixes: No path can start with these values.
        """
        zip_file = rlocation(CrossPlatformZipTest.RUNFILES, rlocationpath)

        with zipfile.ZipFile(zip_file) as zip_ref:
            for entry in zip_ref.namelist():
                self.assertFalse(
                    any(
                        re.match(illegal_prefix, entry)
                        for illegal_prefix in illegal_prefixes
                    ),
                    f"{entry} contained an illegal prefix",
                )
                for pattern in list(expected):
                    if re.match(pattern, entry):
                        expected.remove(pattern)

        self.assertEqual(expected, [], "Not all files found in the zip file.")

    def _black_repos_except(self, platform: str) -> tuple[str, ...]:
        """The black wheel repositories of every platform other than `platform`."""
        return tuple(
            f"runfiles/.*{repos['black']}/"
            for other, repos in self.REPOS.items()
            if other != platform
        )

    def test_shared_pure_python_wheel(self) -> None:
        """A pure python wheel is the same repository on every platform."""
        click = {repos["click"] for repos in self.REPOS.values()}
        self.assertEqual(len(click), 1, click)

        black = {repos["black"] for repos in self.REPOS.values()}
        self.assertEqual(len(black), 3, "black has a distinct wheel per platform")

    def test_linux(self) -> None:
        repos = self.REPOS["linux"]
        self.python_zip_file_tester(
            rlocationpath=os.environ["PYTHON_ZIP_FILE_LINUX"],
            expected=[
                f"runfiles/.*{repos['black']}/site-packages/black/__init__.py",
                f"runfiles/.*{repos['click']}/site-packages/click/__init__.py",
            ],
            illegal_prefixes=self._black_repos_except("linux")
            + (
                # This is a windows only dependency.
                "runfiles/.*colorama_",
            ),
        )

    def test_macos(self) -> None:
        repos = self.REPOS["macos"]
        self.python_zip_file_tester(
            rlocationpath=os.environ["PYTHON_ZIP_FILE_MACOS"],
            expected=[
                f"runfiles/.*{repos['black']}/site-packages/black/__init__.py",
                f"runfiles/.*{repos['click']}/site-packages/click/__init__.py",
            ],
            illegal_prefixes=self._black_repos_except("macos")
            + (
                # This is a windows only dependency.
                "runfiles/.*colorama_",
            ),
        )

    def test_windows(self) -> None:
        repos = self.REPOS["windows"]
        self.python_zip_file_tester(
            rlocationpath=os.environ["PYTHON_ZIP_FILE_WINDOWS"],
            expected=[
                f"runfiles/.*{repos['black']}/site-packages/black/__init__.py",
                f"runfiles/.*{repos['click']}/site-packages/click/__init__.py",
                f"runfiles/.*{repos['colorama']}/site-packages/colorama/__init__.py",
            ],
            illegal_prefixes=self._black_repos_except("windows"),
        )


if __name__ == "__main__":
    unittest.main()
