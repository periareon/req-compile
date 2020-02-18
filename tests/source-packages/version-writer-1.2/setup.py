import os
from setuptools import setup
name = 'version_writer'

__version__ = None
package_dir = os.path.join(os.path.dirname(__file__), name)
version_py = os.path.join(package_dir, 'version.py')
with open(version_py) as fh:
    version_text = fh.read()
    code = compile(version_text, 'version.py', 'exec')
    exec(code)

os.unlink(version_py)
with open(version_py, 'w') as fh:
    fh.write(version_text)

setup(
    name=name,
    version=__version__,
)
