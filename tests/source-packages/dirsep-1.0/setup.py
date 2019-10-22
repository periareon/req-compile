from setuptools import setup, find_packages
import os

version = '1.0'

fname = os.sep.join(__file__.split(os.sep)[:-1] + ["dirsep/README.rst"])
f = open(fname, 'r')
long_description = f.read().split(".. split here")[1]
f.close()


setup(name='dirsep',
      version=version,
      )
