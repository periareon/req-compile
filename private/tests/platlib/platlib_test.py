"""The simple integration test"""

import unittest

from clang.enumerations import TokenKinds  # pylint: disable=import-error


class IntegrationTest(unittest.TestCase):
    def test_importable(self) -> None:
        assert isinstance(TokenKinds, list)


if __name__ == "__main__":
    unittest.main()
