"""The sdist integration test"""

import unittest

from pyspark import __version__  # pylint: disable=import-error


class IntegrationTest(unittest.TestCase):
    def test_version(self) -> None:
        assert __version__ == "3.5.1"


if __name__ == "__main__":
    unittest.main()
