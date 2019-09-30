# -*- coding: utf-8 -*-
import sys
import os

from setuptools import setup, find_packages
from setuptools.command import easy_install
from distutils.extension import Extension

try:
    from Cython.Compiler.Main import compile
    from Cython.Distutils import build_ext
    has_cython = True
except ImportError:
    has_cython = False


C_LIBRARIES = ['estr', 'ee', 'lognorm']
COMPILER_ARGS = list()
LINKER_ARGS = list()


def module_files(module_name, *extensions):
    found = list()
    filename_base = module_name.replace('.', '/')
    for extension in extensions:
        filename = '{}.{}'.format(filename_base, extension)
        if os.path.isfile(filename):
            found.append(filename)
    return found


def fail_build(reason, code=1):
    print(reason)
    raise ValueError(reason)
    sys.exit(code)


def cythonize():
    if not has_cython:
        fail_build('In order to build this project, cython is required.')

    for module in read('./tools/cython-modules'):
        for cython_target in module_files(module, 'pyx', 'pyd'):
            compile(cython_target)


def package_c():
    missing_modules = list()
    extensions = list()

    for module in read('./tools/cython-modules'):
        c_files = module_files(module, 'c')
        if len(c_files) > 0:
            c_ext = Extension(
                module,
                c_files,
                libraries=C_LIBRARIES,
                extra_compile_args=COMPILER_ARGS,
                extra_link_args=LINKER_ARGS)
            extensions.append(c_ext)
        else:
            missing_modules.append(module)

    if len(missing_modules) > 0:
        fail_build('Missing C files for modules {}'.format(missing_modules))
    return extensions


def read(relative):
    contents = open(relative, 'r').read()
    return [l for l in contents.split('\n') if l != '']


# Got tired of fighting build_ext
if 'build' in sys.argv:
    cythonize()

ext_modules = package_c()


setup(
    name='cython-check',
    version='1.0',
    install_requires=read('./tools/install-requires'),
    ext_modules=ext_modules
)
