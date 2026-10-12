"""Check which dependencies the `requests` target of a hub provides."""

import importlib
import sys
import unittest

import requests  # pylint: disable=import-error

EXPECT_SOCKS = "--expect-socks" in sys.argv


class ExtrasTest(unittest.TestCase):
    def test_socks(self) -> None:
        self.assertEqual(requests.__version__, "2.32.3")
        try:
            importlib.import_module("socks")
            has_socks = True
        except ImportError:
            has_socks = False
        self.assertEqual(has_socks, EXPECT_SOCKS)


if __name__ == "__main__":
    sys.argv = [
        arg for arg in sys.argv if arg not in ("--expect-socks", "--no-expect-socks")
    ]
    unittest.main()
