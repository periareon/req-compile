from __future__ import print_function

import functools
import io
import os
import sys
import tarfile
import types
import zipfile
import tempfile
import copy
from contextlib import contextmanager, closing
from types import ModuleType

import setuptools

import pkg_resources
import six

from qer import utils
from qer.dists import DistInfo


def extract_metadata(dist, extras=()):
    """"""
    if dist.lower().endswith('.whl'):
        return _fetch_from_wheel(dist, extras=extras)
    if dist.lower().endswith('.zip'):
        return _fetch_from_zip(dist, extras=extras)
    elif dist.lower().endswith('.tar.gz'):
        return _fetch_from_source(dist, extras=extras)


def _fetch_from_zip(zip_file, extras):
    zfile = zipfile.ZipFile(zip_file, 'r')
    try:
        metadata_file = None
        pkg_info_file = None
        egg_info = None

        for name in zfile.namelist():
            if name.lower().endswith('pkg-info'):
                pkg_info_file = name
            elif name.lower().endswith('.egg-info'):
                egg_info = name
            elif name.lower().endswith('metadata'):
                metadata_file = name

        if egg_info:
            filename = os.path.basename(zip_file)
            name = '-'.join(filename.split('-')[0:-1])
            version = utils.parse_version(filename.split('-')[-1].replace('.tar.gz', ''))
            return _parse_requires_file(zip_file.extractfile(egg_info + '/requires.txt').read(),
                                        name,
                                        version,
                                        extras)

        if pkg_info_file:
            return _parse_flat_metadata(zfile.read(pkg_info_file).decode('utf-8'), extras)

        if metadata_file:
            return _parse_flat_metadata(zfile.read(metadata_file).decode('utf-8'), extras)
    finally:
        zfile.close()


def _fetch_from_source(tar_gz, extras):
    """

    Args:
        tar_gz (str): Source file
        extras:

    Returns:

    """
    tar = tarfile.open(tar_gz, "r:gz")
    filename = os.path.basename(tar_gz)
    name = '-'.join(filename.split('-')[0:-1])
    try:
        metadata_file = None
        pkg_info_file = None
        egg_info = None

        for info in tar.getmembers():
            info_name = info.name.lower()
            if info_name.endswith('pkg-info'):
                pkg_info_file = info.name
            elif info_name.endswith('.egg-info/requires.txt'):
                egg_info = info.name
            elif info_name.endswith('metadata'):
                metadata_file = info.name

            if info_name.endswith('setup.py'):
                setup_file = info.name

        results = None
        if egg_info:
            version = utils.parse_version(filename.split('-')[-1].replace('.tar.gz', ''))
            requires_contents = ''
            try:
                requires_contents = tar.extractfile(egg_info).read().decode('utf-8')
            except KeyError:
                pass
            return _parse_requires_file(requires_contents,
                                        name,
                                        version,
                                        extras)

        if pkg_info_file:
            results = _parse_flat_metadata(
                tar.extractfile(pkg_info_file).read().decode('utf-8'), extras)

        if not results.reqs and setup_file:
            setup_results = _parse_setup_py(name, functools.partial(_opener, tar, os.path.dirname(setup_file), io.open), extras)
            if results:
                setup_results.version = results.version
            return setup_results

        if metadata_file:
            return _parse_flat_metadata(
                tar.extractfile(metadata_file).read().decode('utf-8'), extras)
    finally:
        tar.close()


def _fetch_from_wheel(wheel, extras):
    zfile = zipfile.ZipFile(wheel, 'r')
    try:
        metadata_file = None
        infos = zfile.namelist()
        for info in infos:
            if info.lower().endswith('metadata'):
                metadata_file = info

        if metadata_file:
            return _parse_flat_metadata(zfile.read(metadata_file).decode('utf-8'), extras)
    finally:
        zfile.close()


def _parse_flat_metadata(contents, extras):
    name = None
    version = None
    raw_reqs = []

    for line in contents.split('\n'):
        if line.lower().startswith('name:'):
            name = line.split(':')[1].strip()
        if line.lower().startswith('version:'):
            version = utils.parse_version(line.split(':')[1].strip())
        if line.lower().startswith('requires-dist:'):
            raw_reqs.append(line.split(':')[1].strip())

    return DistInfo(name, version, list(utils.parse_requirements(raw_reqs)), extras=extras)


def _opener(tar, directory, direct, filename, mode='r', encoding=None):
    filename = filename.replace('\\', '/')
    if not os.path.isabs(filename):
        try:
            return with_decoding(tar.extractfile(directory + '/' + filename), encoding=encoding)
        except KeyError:
            raise IOError('Not found')
    else:
        return direct(filename, mode=mode, encoding=encoding)


class with_decoding(object):
    def __init__(self, wrap, encoding):
        self.file = wrap
        self.encoding = encoding

    def read(self):
        results = self.file.read()
        if self.encoding:
            results = results.decode(self.encoding)
        return results

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def close(self):
        pass


def setup(results, *args, **kwargs):
    name = kwargs.get('name', None)
    version = kwargs.get('version', None)
    reqs = kwargs.get('install_requires', [])

    results.append(DistInfo(name, version,
                            list(utils.parse_requirements(reqs))))


class FakeModule(types.ModuleType):
    def __getitem__(self, item):
        return None

    def __getattr__(self, item):
        return None


def fake_import(name, orig_import, modname, *args, **kwargs):
    if name.lower() == modname.lower():
        print('Its trying to import itself {}'.format(modname))
        sys.modules[modname] = FakeModule(modname)
    return orig_import(modname, *args, **kwargs)

def _parse_setup_py(name, opener, extras):
    import setuptools
    import distutils.core
    import sys
    sys.exit = lambda code: None

    results = []
    setup_with_results = functools.partial(setup, results)

    old_open = io.open
    io.open = opener
    spy_globals = {'__file__': '',
                   '__name__': '__main__',
                   'open': opener,
                   'setup': setup_with_results,
                   'fake_import': functools.partial(fake_import, name, __import__)}

    setuptools.setup = setup_with_results
    distutils.core.setup = setup_with_results
    contents = opener('setup.py', encoding='utf-8').read()
    try:
        lines = contents.split('\n')
        if six.PY2:
            lines = [line for line in lines if not (line.startswith('#') and
                                                    ('-*- coding' in line or '-*- encoding' in line))]

        idx = 0
        line = lines[0].strip()
        while not line or line.startswith('#') or '__future__' in line:
            idx += 1
            line = lines[idx].strip()
        if six.PY2:
            lines.insert(idx, 'import __builtin__; __builtin__.__import__ = fake_import\n')
        else:
            lines.insert(idx, 'import builtins; builtins.__import__ = fake_import\n')
        contents = '\n'.join(lines)
        exec(contents, spy_globals, spy_globals)
    except:
        raise
    finally:
        io.open = old_open
    if not results:
        pass
    return results[0]


def _parse_requires_file(contents, name, version, extras):
    reqs = []
    sections = list(pkg_resources.split_sections(contents))
    for section in sections:
        if section[0] is None:
            reqs.extend(utils.parse_requirements(section[1]))
        elif section[0].startswith(':python_version'):
            for req in section[1]:
                reqs.append(utils.parse_requirement(req + ' ' + section[0].replace(':', ';')))

    return DistInfo(name, version, reqs)
