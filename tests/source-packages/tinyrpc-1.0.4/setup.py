import os

from setuptools import setup


def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()


setup(
    name="tinyrpc", version="1.0.4", install_requires=["six"],
)
