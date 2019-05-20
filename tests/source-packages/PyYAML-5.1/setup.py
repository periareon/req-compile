
NAME = 'PyYAML'
VERSION = '5.1'

LIBYAML_CHECK = """
#include <yaml.h>

int main(void) {
    yaml_parser_t parser;
    yaml_emitter_t emitter;

    yaml_parser_initialize(&parser);
    yaml_parser_delete(&parser);

    yaml_emitter_initialize(&emitter);
    yaml_emitter_delete(&emitter);

    return 0;
}
"""


import sys, os.path, platform, warnings

from distutils import log
from distutils.core import setup, Command
from distutils.core import Distribution as _Distribution
from distutils.core import Extension as _Extension
from distutils.dir_util import mkpath
from distutils.command.build_ext import build_ext as _build_ext
from distutils.command.bdist_rpm import bdist_rpm as _bdist_rpm
from distutils.errors import DistutilsError, CompileError, LinkError, DistutilsPlatformError

if 'setuptools.extension' in sys.modules:
    _Extension = sys.modules['setuptools.extension']._Extension
    sys.modules['distutils.core'].Extension = _Extension
    sys.modules['distutils.extension'].Extension = _Extension
    sys.modules['distutils.command.build_ext'].Extension = _Extension

with_cython = False
if 'sdist' in sys.argv:
    # we need cython here
    with_cython = True
try:
    from Cython.Distutils.extension import Extension as _Extension
    from Cython.Distutils import build_ext as _build_ext
    with_cython = True
except ImportError:
    if with_cython:
        raise

try:
    from wheel.bdist_wheel import bdist_wheel
except ImportError:
    bdist_wheel = None


# on Windows, disable wheel generation warning noise
windows_ignore_warnings = [
"Unknown distribution option: 'python_requires'",
"Config variable 'Py_DEBUG' is unset",
"Config variable 'WITH_PYMALLOC' is unset",
"Config variable 'Py_UNICODE_SIZE' is unset",
"Cython directive 'language_level' not set"
]

if platform.system() == 'Windows':
    for w in windows_ignore_warnings:
        warnings.filterwarnings('ignore', w)

class Distribution(_Distribution):

    def __init__(self, attrs=None):
        _Distribution.__init__(self, attrs)


class Extension(_Extension):

    def __init__(self, name, sources, feature_name, feature_description,
            feature_check, **kwds):
        if not with_cython:
            for filename in sources[:]:
                base, ext = os.path.splitext(filename)
                if ext == '.pyx':
                    sources.remove(filename)
                    sources.append('%s.c' % base)
        _Extension.__init__(self, name, sources, **kwds)

class test(Command):

    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        build_cmd = self.get_finalized_command('build')
        build_cmd.run()
        sys.path.insert(0, build_cmd.build_lib)
        if sys.version_info[0] < 3:
            sys.path.insert(0, 'tests/lib')
        else:
            sys.path.insert(0, 'tests/lib3')
        import test_all
        if not test_all.main([]):
            raise DistutilsError("Tests failed")

if __name__ == '__main__':
    setup(
        name=NAME,
        version=VERSION,
        package_dir={'': {2: 'lib', 3: 'lib3'}[sys.version_info[0]]},
        packages=['yaml'],
        ext_modules=[
            Extension('_yaml', ['ext/_yaml.pyx'],
                'libyaml', "LibYAML bindings", LIBYAML_CHECK,
                libraries=['yaml']),
        ],
        distclass=Distribution,
        python_requires='>=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*',
    )
