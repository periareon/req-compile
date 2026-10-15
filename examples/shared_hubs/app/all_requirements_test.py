"""Check `all_requirements` only provides the packages of the current platform."""

import importlib
import sys
import unittest


class AllRequirementsTest(unittest.TestCase):
    def test_platform_packages(self) -> None:
        importlib.import_module("click")
        importlib.import_module("requests")
        importlib.import_module("socks")

        try:
            importlib.import_module("colorama")
            has_colorama = True
        except ImportError:
            has_colorama = False
        self.assertEqual(has_colorama, sys.platform == "win32")


if __name__ == "__main__":
    unittest.main()
