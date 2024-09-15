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


class CrossPlatformZipTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.RUNFILES = Runfiles.Create()
        if not cls.RUNFILES:
            raise EnvironmentError("Failed to locate runfiles.")

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

    def test_linux(self) -> None:
        self.python_zip_file_tester(
            rlocationpath=os.environ["PYTHON_ZIP_FILE_LINUX"],
            expected=[
                "runfiles/.*_linux__black/site-packages/black/__init__.py",
            ],
            illegal_prefixes=(
                "runfiles/.*_platform_macos__",
                "runfiles/.*_windows__",
                # This is a windows only dependency.
                "runfiles/.*_linux__colorama",
            ),
        )

    def test_macos(self) -> None:
        self.python_zip_file_tester(
            rlocationpath=os.environ["PYTHON_ZIP_FILE_MACOS"],
            expected=[
                "runfiles/.*_macos__black/site-packages/black/__init__.py",
            ],
            illegal_prefixes=(
                "runfiles/.*_linux__",
                "runfiles/.*_windows__",
                # This is a windows only dependency.
                "runfiles/.*_macos__colorama",
            ),
        )

    def test_windows(self) -> None:
        self.python_zip_file_tester(
            rlocationpath=os.environ["PYTHON_ZIP_FILE_WINDOWS"],
            expected=[
                "runfiles/.*_windows__black/site-packages/black/__init__.py",
                "runfiles/.*_windows__colorama/site-packages/colorama/__init__.py",
            ],
            illegal_prefixes=(
                "runfiles/.*_linux__",
                "runfiles/.*_macos__",
            ),
        )


if __name__ == "__main__":
    unittest.main()
