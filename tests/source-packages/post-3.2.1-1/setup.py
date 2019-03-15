#!/usr/bin/python

import sys
from distutils.core import setup


def main():
    if not (3,) > sys.version_info >= (2, 7):
        sys.stderr.write('This backport is for Python 2.7 only.\n')
        sys.exit(1)

    setup(
      name='post',
      version='3.2.1-1',
      description='',
      long_description="""""",
      license='PSF license',
      maintainer='',
      maintainer_email='',
      url='',
    )


if __name__ == '__main__':
    main()
