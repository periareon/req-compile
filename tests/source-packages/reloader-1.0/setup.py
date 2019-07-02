try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

version = __import__('reloader').__version__

setup(
    name = 'reloader',
    version = version,
    download_url = 'URL' + version,
)
