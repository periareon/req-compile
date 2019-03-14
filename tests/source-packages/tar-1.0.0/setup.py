from setuptools import setup

setup(
    name='tar',
    version='1.0.0',
    install_requires=open('requirements.txt').readlines()
)
