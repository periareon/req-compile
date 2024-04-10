"""The sdist integration test"""

import unittest

from numpy import __version__ as numpy_version  # pylint: disable=import-error
from sphinx import __version__ as sphinx_version  # pylint: disable=import-error


class IntegrationTest(unittest.TestCase):
    def test_numpy_version(self) -> None:
        assert numpy_version == "1.26.4"

    def test_sphinx_version(self) -> None:
        assert sphinx_version == "7.2.6"


if __name__ == "__main__":
    unittest.main()
