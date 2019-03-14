#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys

try:
    reload(sys).setdefaultencoding("UTF-8")
except:
    pass

try:
    from setuptools import setup
except ImportError:
    print('Please install or upgrade setuptools or pip to continue')
    sys.exit(1)

import codecs


def read(filename):
    return codecs.open(filename, encoding='utf-8').read()


long_description = '\n\n'.join([read('README'),
                                read('AUTHORS'),
                                read('CHANGES')])

__doc__ = long_description

setup(
    name='Pint',
    version='0.6',
    long_description=long_description,
    zip_safe=True,
    packages=['pint'],
)
