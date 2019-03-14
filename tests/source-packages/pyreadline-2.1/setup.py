
#*****************************************************************************
#  Distributed under the terms of the BSD License.  The full license is in
#  the file COPYING, distributed as part of this software.
#*****************************************************************************

import os
import sys
import glob
from distutils.core import setup

# BEFORE importing distutils, remove MANIFEST. distutils doesn't properly
# update it when the contents of directories change.
if os.path.exists('MANIFEST'): os.remove('MANIFEST')
#

exec(compile(open('pyreadline/release.py').read(), 'pyreadline/release.py', 'exec'))

try:
    import sphinx
    from sphinx.setup_command import BuildDoc
    cmd_class ={'build_sphinx': BuildDoc}
except ImportError:
    cmd_class = {}

packages = ['pyreadline']

setup(name=name,
      version          = version,
      description      = description,
      long_description = long_description,
      license          = license,
      classifiers      = classifiers,
      keywords         = keywords,
      py_modules       = ['readline'],
      packages         = packages,
      package_data     = {'pyreadline':['configuration/*']},
      data_files       = [],
      cmdclass = cmd_class
      )
