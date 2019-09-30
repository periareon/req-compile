import sys, os
from warnings import warn
from distutils import log
from distutils.command.build_ext import build_ext as _build_ext
from version import get_git_version

try:
    from setuptools import setup, Extension
except ImportError as ex:
    from ez_setup import use_setuptools
    use_setuptools()

    from setuptools import setup, Extension

setup(
    name='ez-setup-test',
    version='1.0',
)
