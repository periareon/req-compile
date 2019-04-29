#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import absolute_import, with_statement
import os
import sys
import codecs
from setuptools import setup, find_packages

# Change to source's directory prior to running any command
try:
    SETUP_DIRNAME = os.path.dirname(__file__)
except NameError:
    # We're most likely being frozen and __file__ triggered this NameError
    # Let's work around that
    SETUP_DIRNAME = os.path.dirname(sys.argv[0])

if SETUP_DIRNAME != '':
    os.chdir(SETUP_DIRNAME)


def read(fname):
    '''
    Read a file from the directory where setup.py resides
    '''
    file_path = os.path.join(SETUP_DIRNAME, fname)
    with codecs.open(file_path, encoding='utf-8') as rfh:
        return rfh.read()


# Version info -- read without importing
_LOCALS = {}
with open(os.path.join(SETUP_DIRNAME, 'ptl', 'version.py')) as rfh:
    exec(rfh.read(), None, _LOCALS)  # pylint: disable=exec-used


VERSION = _LOCALS['__version__']
LONG_DESCRIPTION = read('README.rst')

setup(
    name='ptl',
    version=VERSION,
    author='',
    author_email='',
    maintainer='',
    maintainer_email='',
    license='MIT',
    url='',
    description='',
    long_description=LONG_DESCRIPTION,
    packages=find_packages(),
    install_requires=['pytest>=2.8.1'],
)
