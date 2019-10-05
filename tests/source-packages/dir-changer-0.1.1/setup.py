#!/usr/bin/env python

import setuptools
import os
from os.path import abspath, dirname

print('FILE = {}'.format(__file__))
print('DIR = {}'.format(dirname(abspath(__file__))))
os.chdir(dirname(abspath(__file__)))

setuptools.setup(
    name='dir-changer',
    version='0.1.1',
    long_description=open('README.md').read(),
    install_requires=['requests'],
)
