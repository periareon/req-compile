#!/usr/bin/env python
# -*- coding: utf-8 -*-

gdal_version = '3.0.1'

import sys
import os

from glob import glob
from distutils.sysconfig import get_config_vars
from distutils.command.build_ext import build_ext
from distutils.ccompiler import get_default_compiler
from distutils.errors import CompileError

HAVE_NUMPY = False
HAVE_SETUPTOOLS = False


def get_numpy_include():
    if HAVE_NUMPY:
        return numpy.get_include()
    return '.'


try:
    import numpy
    HAVE_NUMPY = True
    # check version
    numpy_major = numpy.__version__.split('.')[0]
    if int(numpy_major) < 1:
        print("numpy version must be > 1.0.0")
        HAVE_NUMPY = False
    else:
        #  print ('numpy include', get_numpy_include())
        if get_numpy_include() == '.':
            print("WARNING: numpy headers were not found!  Array support will not be enabled")
            HAVE_NUMPY = False
except ImportError:
    print('WARNING: numpy not available!  Array support will not be enabled')
    pass


from setuptools import setup
HAVE_SETUPTOOLS = True

name = 'GDAL'
version = gdal_version
license_type = "MIT"
url = "http://www.gdal.org"

classifiers = [
    'Development Status :: 5 - Production/Stable',
]

setup_kwargs = dict(
    name=name,
    version=gdal_version,
    long_description_content_type='text/x-rst',
    license=license_type,
    classifiers=classifiers,
    url=url,
    scripts=glob('scripts/*.py'),
)

# This section can be greatly simplified with python >= 3.5 using **
if HAVE_SETUPTOOLS:
    setup_kwargs['zip_safe'] = False
    setup(**setup_kwargs)
else:
    setup(**setup_kwargs)
