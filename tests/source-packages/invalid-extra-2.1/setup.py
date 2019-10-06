import sys
from setuptools import setup

extra = {}

if sys.version_info < (2, 7):
    extra['install_requires'] = ['ordereddict>=1.1']


setup(
    name='invalid-extra',
    version='2.1',
    extras_require={
        'Locale': ['Babel>=1.3'],
        ':python_version=="2.6"': ['ordereddict'],
    },
    **extra
)
