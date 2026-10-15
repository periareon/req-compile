"""Check that annotations declared by a dependency module are applied."""

import os
import unittest
from pathlib import Path

from python.runfiles import Runfiles  # pylint: disable=import-error


class DependencyAnnotationsTest(unittest.TestCase):
    def test_marker_from_dependency(self) -> None:
        runfiles = Runfiles.Create()
        assert runfiles, "Failed to locate runfiles"
        # `source_repo` is given explicitly because the default inspects the call stack
        # and fails when this script and the runfiles library live on different drives,
        # which is the case under `rules_venv` on the Windows CI runners.
        marker = runfiles.Rlocation(os.environ["LIB_MARKER"], source_repo="")
        assert marker, "Failed to find the annotation marker"
        self.assertTrue(Path(marker).exists(), marker)
        self.assertIn("annotated_by_lib.txt", marker)


if __name__ == "__main__":
    unittest.main()
