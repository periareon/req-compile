import os
from distutils.core import setup

prjdir = os.path.dirname(__file__)

def read(filename):
    return open(os.path.join(prjdir, filename)).read()

LONG_DESC = read('README.rst') + '\nCHANGES\n=======\n\n' + read('CHANGES.rst')

from termcolor import VERSION

setup(name='termcolor',
      version='.'.join([str(v) for v in VERSION]),
      description='ANSII Color formatting for output in terminal.',
      long_description=LONG_DESC,
      author='Konstantin Lepa',
      license='MIT',
      author_email='konstantin.lepa@gmail.com',
      url='http://pypi.python.org/pypi/termcolor',
      py_modules=['termcolor'])
