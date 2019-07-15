from setuptools import setup, find_packages
import numpy

from Cython.Build import cythonize

name = 'pkg-with-cython'

setup(
    setup_requires=['cython', 'numpy'],
    name=name,
    version='1.0',
    ext_modules=cythonize(['pkg/extension.pyx']),
    include_dirs=[numpy.get_include()],
    packages=find_packages(include=[name + '*']),
    install_requires=['numpy'],
)
