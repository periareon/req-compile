from re import sub

from setuptools import setup, find_packages


def get_long_description():
    # Fix display issues on PyPI caused by RST markup
    readme = open('README.rst').read()

    version_lines = []
    with open('docs/versions.rst') as infile:
        next(infile)
        for line in infile:
            version_lines.append(line)
    version_history = '\n'.join(version_lines)

    ret = readme + '\n\n' + version_history
    return ret


setup(
    name='mtt',
    version='7.0.0',
    long_description=get_long_description(),
    license='MIT',
    python_requires='>=3.4',
    test_suite='more_itertools.tests',
    url='https://github.com/erikrose/more-itertools',
    include_package_data=True,
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3 :: Only',
        'Topic :: Software Development :: Libraries'],
    keywords=['itertools', 'iterator', 'iteration', 'filter', 'peek',
              'peekable', 'collate', 'chunk', 'chunked'],
)
