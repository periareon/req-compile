"""Check that an annotation scoped to one hub only affects that hub."""

import os
import unittest
from pathlib import Path

from python.runfiles import Runfiles  # pylint: disable=import-error
from runfiles_util import runfiles_repositories  # pylint: disable=import-error


class ScopedAnnotationsTest(unittest.TestCase):
    def test_marker_applied_to_app_hub(self) -> None:
        runfiles = Runfiles.Create()
        assert runfiles, "Failed to locate runfiles"
        # `source_repo` is given explicitly because the default inspects the call stack
        # and fails when this script and the runfiles library live on different drives,
        # which is the case under `rules_venv` on the Windows CI runners.
        marker = runfiles.Rlocation(os.environ["APP_MARKER"], source_repo="")
        assert marker, "Failed to find the annotation marker"
        self.assertTrue(Path(marker).exists(), marker)

    def test_repositories_split_by_annotation(self) -> None:
        """Both hubs depend on `idna` through `requests`, but annotate it differently."""
        repositories = runfiles_repositories()
        idna = sorted(repo for repo in repositories if "+idna_" in repo)
        self.assertEqual(len(idna), 2, idna)

        # The dependency's `urllib3` annotation has no `hubs`, so it applies to the
        # dependency's hub only and the two hubs no longer share that repository.
        urllib3 = sorted(repo for repo in repositories if "+urllib3_" in repo)
        self.assertEqual(len(urllib3), 2, urllib3)

        # Wheels annotated the same way, or not at all, are still shared.
        requests = sorted(repo for repo in repositories if "+requests_" in repo)
        self.assertEqual(len(requests), 1, requests)


if __name__ == "__main__":
    unittest.main()
