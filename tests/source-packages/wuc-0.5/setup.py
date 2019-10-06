import os.path as path
from io import open  # PY2
from setuptools import setup

ENCODING = "UTF-8"
HERE = path.abspath(path.dirname(__file__))


def read(*relative_path_parts):
    with open(path.join(HERE, *relative_path_parts), encoding=ENCODING) as f:
        return f.read()


VERSION = "0.5"
README = "README.rst"

setup(
    name="wuc",
    version=VERSION,
    long_description=read(README),
)
