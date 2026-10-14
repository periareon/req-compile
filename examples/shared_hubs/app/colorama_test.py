"""Only runs on Windows, the only platform whose lock contains colorama."""

import sys
import unittest

import colorama  # pylint: disable=import-error


class ColoramaTest(unittest.TestCase):
    def test_platform(self) -> None:
        self.assertEqual(sys.platform, "win32")
        self.assertEqual(colorama.__version__, "0.4.6")


if __name__ == "__main__":
    unittest.main()
