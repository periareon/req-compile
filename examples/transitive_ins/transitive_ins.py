"""The transitive_ins integration test"""

import unittest

from toml import __version__ as toml_version
from tomli import __version__ as tomli_version
from yaml import __version__ as yaml_version


class IntegrationTest(unittest.TestCase):
    def test_versions(self) -> None:
        assert toml_version == "0.10.2"
        assert tomli_version == "2.0.1"
        assert yaml_version == "6.0.1"


if __name__ == "__main__":
    unittest.main()
