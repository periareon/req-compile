import functools
import sys

from req_compile.importhook import import_hook
from req_compile.metadata import patch

import setuptools
import setuptools.extern

fake_import = functools.partial(import_hook, open)

with patch('builtins', '__import__', fake_import), \
     patch('__builtin__', '__import__', fake_import):
    exec(open(sys.argv[1]).read())
