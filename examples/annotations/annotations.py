"""The annotations integration test"""

import os
import unittest
from pathlib import Path

from numpy import __version__ as numpy_version  # pylint: disable=import-error
from numpy.__config__ import req_comple_annotation  # pylint: disable=import-error
from python.runfiles import Runfiles  # pylint: disable=import-error
from sphinx import __version__ as sphinx_version  # pylint: disable=import-error


class IntegrationTest(unittest.TestCase):
    def test_numpy_version(self) -> None:
        assert numpy_version == "1.26.4"

    def test_sphinx_version(self) -> None:
        assert sphinx_version == "7.2.6"

    def test_patches_annotation(self) -> None:
        assert req_comple_annotation == "req-compile"

    def test_copy_annotations(self) -> None:
        runfiles = Runfiles.Create()
        assert runfiles, "Failed to locate runfiles"

        # The wheel is shared by every platform that pins the same file, so the
        # repository holding it is found from the wheel rather than hard coded.
        repository, _, _ = os.environ["NUMPY_WHEEL"].partition("/")

        expected = [
            f"{repository}/site-packages/numpy/conftest.copy.py",
            f"{repository}/site-packages/numpy-1.26.4.dist-info/entry_points.copy.txt",
            f"{repository}/site-packages/numpy/testing/setup.copy.py",
        ]

        for rlocationpath in expected:
            runfile = runfiles.Rlocation(rlocationpath)
            assert runfile, f"Failed to find runfile: {rlocationpath}"
            assert Path(runfile).exists(), f"Runfile does not exist: {rlocationpath}"


if __name__ == "__main__":
    unittest.main()
