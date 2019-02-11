from setuptools import setup, find_packages

setup(
    name='qer',
    version='0.1.0',
    author='Spencer Putt',
    author_email='sputt@alumni.iu.edu',
    description='Python requirements compiler',
    install_requires=open('requirements.txt').readlines(),
    packages=find_packages(include=['qer*']),
    license='Public Domain',
    entry_points={
        'console_scripts': [
            'req-compile = qer.cmdline:compile_main',
            'req-hash = qer.hash:hash_main',
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 2",
        "Operating System :: OS Independent",
    ],
)
