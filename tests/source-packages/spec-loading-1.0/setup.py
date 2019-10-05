import os

from setuptools import setup

here = os.path.abspath(os.path.dirname(__file__))
try:
    with open(os.path.join(here, 'README.rst')) as f:
        README = f.read()
except IOError:
    README = ''

from importlib.util import module_from_spec, spec_from_file_location

spec = spec_from_file_location("constants", "./spec/_constants.py")
constants = module_from_spec(spec)
spec.loader.exec_module(constants)

__author__ = constants.__author__
__author_email__ = constants.__author_email__
__license__ = constants.__license__
__maintainer_email__ = constants.__maintainer_email__
__url__ = constants.__url__
__version__ = constants.__version__

setup(
    name='spec-loading',
    version=__version__,
    long_description=README,
    author=__author__,
    author_email=__author_email__,
    url=__url__,
    license=__license__,
    install_requires=[
        'jdcal', 'et_xmlfile',
    ],
)
