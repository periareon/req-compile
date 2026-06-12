"""The simple integration test"""

import unittest

from wheel import __version__


class IntegrationTest(unittest.TestCase):
    def test_version(self) -> None:
        assert __version__ == "0.43.0"


if __name__ == "__main__":
    unittest.main()
