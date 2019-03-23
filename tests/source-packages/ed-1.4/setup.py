from __future__ import print_function
import sys, os, timeit
from distutils.core import setup, Extension, Command
from distutils.util import get_platform
import versioneer

LONG_DESCRIPTION="""\
"""

commands = versioneer.get_cmdclass().copy()

sources = ["src/ref.c"]
sources.extend(["src/benchmark/"+s
                for s in os.listdir("src/benchmark")
                if s.endswith(".c") and s!="test.c"])

m = Extension("ed._ed",
              include_dirs=["src/benchmark"], sources=sources)

class Test(Command):
    description = "run tests"
    user_options = []
    def initialize_options(self):
        pass
    def finalize_options(self):
        pass
    def setup_path(self):
        # copied from distutils/command/build.py
        self.plat_name = get_platform()
        plat_specifier = ".%s-%s" % (self.plat_name, sys.version[0:3])
        self.build_lib = os.path.join("build", "lib"+plat_specifier)
        sys.path.insert(0, self.build_lib)
    def run(self):
        pass

commands["test"] = Test


setup(name="ed",
      version=versioneer.get_version(),
      description="",
      long_description=LONG_DESCRIPTION,
      author="",
      author_email="",
      license="MIT",
      url="",
      ext_modules=[m],
      packages=["ed"],
      package_dir={"ed": "src/ref"},
      cmdclass=commands,
      )
