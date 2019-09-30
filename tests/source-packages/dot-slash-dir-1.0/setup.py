import os
import sys

HERE = os.path.dirname(sys.argv[0]) or "."

import setuptools

version = open(os.path.join(HERE, "__init__.py")).read().split('VERSION = "', 1)[1].split('"', 1)[0]

setuptools.setup(
    name="dot-slash-dir",
    version=version
)
