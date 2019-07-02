from setuptools import setup, find_packages

setup(
    name='qer',
    version='0.8.0',
    author='Spencer Putt',
    author_email='sputt@alumni.iu.edu',
    description='Python requirements compiler',
    long_description=open('README.rst').read(),
    url='https://github.com/sputt/qer',
    install_requires=open('requirements.txt').readlines(),
    packages=find_packages(include=['qer*']),
    license='MIT License',
    entry_points={
        'console_scripts': [
            'req-compile = qer.cmdline:compile_main',
            'req-hash = qer.hash:hash_main',
            'req-candidates = qer.candidates:candidates_main',
        ],
    },
    extra_requires={
        'test': open('test-requirements.txt').readlines()
    },
    python_requires=">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*",
    classifiers=[
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Operating System :: OS Independent',
        'Environment :: Console',
        'Topic :: Software Development',
        'Intended Audience :: Developers',
        "License :: OSI Approved :: MIT License",
    ],
)
