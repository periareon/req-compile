#!/usr/bin/env python

import codecs
import sys
import os
import warnings
if sys.version_info < (2, 6):
    raise Exception("Python >= 2.6 is required.")
elif sys.version_info[:2] == (3, 2):
    warnings.warn("Python 3.2 is no longer officially supported")

from setuptools import setup, Extension, find_packages
import re

here = os.path.abspath(os.path.dirname(__file__))
try:
    with codecs.open(os.path.join(here, 'README.rst'), encoding="utf-8") as f:
        README = f.read()
except IOError:
    README = ''

from etxmlf import (
    __author__,
    __license__,
    __author_email__,
    __url__,
    __version__
)


setup(name='etxmlf',
    packages=find_packages(),
    # metadata
    version=__version__,
    description="",
    long_description=README,
    author=__author__,
    author_email=__author_email__,
    url=__url__,
    license=__license__,
    requires=[
        'python (>=2.6.0)',
        ],
    )
