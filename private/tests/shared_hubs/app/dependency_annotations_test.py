"""Check that annotations declared by a dependency module are applied."""

import os
import unittest
from pathlib import Path

from python.runfiles import Runfiles  # pylint: disable=import-error


class DependencyAnnotationsTest(unittest.TestCase):
    def test_marker_from_dependency(self) -> None:
        runfiles = Runfiles.Create()
        assert runfiles, "Failed to locate runfiles"
        marker = runfiles.Rlocation(os.environ["LIB_MARKER"])
        assert marker, "Failed to find the annotation marker"
        self.assertTrue(Path(marker).exists(), marker)
        self.assertIn("annotated_by_lib.txt", marker)


if __name__ == "__main__":
    unittest.main()
