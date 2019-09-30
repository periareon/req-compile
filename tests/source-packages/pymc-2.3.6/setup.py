#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function

from numpy.distutils.misc_util import Configuration
from numpy.distutils.system_info import get_info
import os, sys

config = Configuration('pymc',parent_package=None,top_path=None)
dist = sys.argv[1]


lapack_info = get_info('lapack_opt',1)
f_sources = ['pymc/flib.f','pymc/histogram.f', 'pymc/flib_blas.f', 'pymc/blas_wrap.f', 'pymc/math.f', 'pymc/gibbsit.f', 'cephes/i0.c',
             'cephes/c2f.c','cephes/chbevl.c']
if lapack_info:
    config.add_extension(name='flib',sources=f_sources, extra_info=lapack_info, f2py_options=['skip:ppnd7'])

if not lapack_info or dist in ['bdist', 'sdist']:
    ##inc_dirs = ['blas/BLAS','lapack/double']
    print('No optimized BLAS or Lapack libraries found, building from source. This may take a while...')
    for fname in os.listdir('blas/BLAS'):
        # Make sure this is a Fortran file, and not one of those weird hidden files that
        # pop up sometimes in the tarballs
        if fname[-2:]=='.f' and fname[0].find('_')==-1:
            f_sources.append('blas/BLAS/'+fname)


    for fname in ['dpotrs','dpotrf','dpotf2','ilaenv','dlamch','ilaver','ieeeck','iparmq']:
        f_sources.append('lapack/double/'+fname+'.f')
    config.add_extension(name='flib',sources=f_sources)

config.add_extension(name='LazyFunction',sources=['pymc/LazyFunction.c'])
config.add_extension(name='Container_values', sources='pymc/Container_values.c')

config_dict = config.todict()
try:
    config_dict.pop('packages')
except:
    pass

# Compile linear algebra utilities
if lapack_info:
    config.add_extension(name='gp.linalg_utils',sources=['pymc/gp/linalg_utils.f','pymc/blas_wrap.f'], extra_info=lapack_info)
    config.add_extension(name='gp.incomplete_chol',sources=['pymc/gp/incomplete_chol.f'], extra_info=lapack_info)

if not lapack_info or dist in ['bdist', 'sdist']:
    print('No optimized BLAS or Lapack libraries found, building from source. This may take a while...')
    f_sources = ['pymc/blas_wrap.f']
    for fname in os.listdir('blas/BLAS'):
        if fname[-2:]=='.f':
            f_sources.append('blas/BLAS/'+fname)

    for fname in ['dpotrs','dpotrf','dpotf2','ilaenv','dlamch','ilaver','ieeeck','iparmq']:
        f_sources.append('lapack/double/'+fname+'.f')

    config.add_extension(name='gp.linalg_utils',sources=['pymc/gp/linalg_utils.f'] + f_sources)
    config.add_extension(name='gp.incomplete_chol',sources=['pymc/gp/incomplete_chol.f'] + f_sources)


# Compile covariance functions
config.add_extension(name='gp.cov_funs.isotropic_cov_funs',\
sources=['pymc/gp/cov_funs/isotropic_cov_funs.f','blas/BLAS/dscal.f'],\
extra_info=lapack_info)

config.add_extension(name='gp.cov_funs.distances',sources=['pymc/gp/cov_funs/distances.f'], extra_info=lapack_info)

if __name__ == '__main__':
    from numpy.distutils.core import setup
    setup(  version="2.3.6",
            description="Markov Chain Monte Carlo sampling toolkit.",
            author="Christopher Fonnesbeck, Anand Patil and David Huard",
            author_email="fonnesbeck@gmail.com ",
            url="http://github.com/pymc-devs/pymc",
            license="Academic Free License",
            requires=['NumPy (>=1.8)',],
            packages=["pymc", "pymc/database", "pymc/examples", "pymc/examples/gp", "pymc/tests", "pymc/gp", "pymc/gp/cov_funs"],
            **(config_dict))

