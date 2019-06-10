from __future__ import print_function

import contextlib
import functools
import imp
import io
import logging
import os
import sys
import tarfile
import tempfile
import types
import zipfile
import abc
from contextlib import closing

import pkg_resources
import six
from six.moves import StringIO

from qer import utils
from qer.blacklist import PY2_BLACKLIST
from qer.dists import DistInfo

USE_PROCESS = False

class MetadataError(Exception):
    def __init__(self, name, version, ex):
        self.name = name
        self.version = version
        self.ex = ex

    def __str__(self):
        return 'Failed to parse metadata for package {} ({}) - {}: {}'.format(self.name, self.version, self.ex.__class__.__name__, str(self.ex))


class Extractor(six.with_metaclass(abc.ABCMeta, object)):
    @abc.abstractmethod
    def names(self):
        pass

    @abc.abstractmethod
    def open(self, filename, mode='r', encoding=None):
        pass

    @abc.abstractmethod
    def close(self):
        pass

    def relative_opener(self, fake_root, directory):
        def inner_opener(filename, *args, **kwargs):
            archive_path = filename
            if os.path.isabs(filename):
                if filename.startswith(fake_root):
                    archive_path = os.path.relpath(filename, fake_root)
                else:
                    return self.open(filename, *args, **kwargs)
            return self.open(directory + '/' + archive_path, *args, **kwargs)
        return inner_opener

    def contents(self, name):
        return self.open(name, encoding='utf-8').read()


def parse_source_filename(full_filename):
    filename = full_filename
    filename = filename.replace('.tar.gz', '')
    filename = filename.replace('.zip', '')
    filename = filename.replace('.tgz', '')

    dash_parts = filename.split('-')
    version_start = None
    for idx, part in enumerate(dash_parts):
        if part[0].isdigit():
            version_start = idx
            break

    if version_start is None:
        return os.path.basename(full_filename), None

    if version_start == 0:
        raise ValueError('Package name missing: {}'.format(full_filename))

    pkg_name = '-'.join(dash_parts[:version_start])
    version = utils.parse_version('-'.join(dash_parts[version_start:]))

    return pkg_name, version


class NonExtractor(Extractor):
    def __init__(self, path):
        self.path = path
        self.io_open = io.open

    def names(self):
        parent_dir = os.path.abspath(os.path.join(self.path, '..'))
        for root, dirs, files in os.walk(self.path):
            rel_root = os.path.relpath(root, parent_dir).replace('\\', '/')
            for file in files:
                yield rel_root + '/' + file

    def open(self, filename, mode='r', encoding='utf-8', errors=None):
        if not os.path.isabs(filename):
            parent_dir = os.path.abspath(os.path.join(self.path, '..'))
            return self.io_open(os.path.join(parent_dir, filename), mode=mode, encoding=encoding)
        else:
            return self.io_open(filename, mode=mode, encoding=encoding)

    def close(self):
        pass


class TarExtractor(Extractor):
    def __init__(self, filename):
        self.tar = tarfile.open(filename, 'r:gz')
        self.io_open = io.open

    def names(self):
        return (info.name for info in self.tar.getmembers())

    def open(self, filename, mode='r', encoding='utf-8', errors=None):
        filename = filename.replace('\\', '/').replace('./', '')
        if not os.path.isabs(filename):
            try:
                handle = self.tar.extractfile(filename)
                return with_decoding(handle, encoding=encoding if mode != 'rb' else None)
            except KeyError:
                raise IOError('Not found in archive: {}'.format(filename))
        else:
            return self.io_open(filename, mode=mode, encoding=encoding)

    def close(self):
        self.tar.close()


class ZipExtractor(Extractor):
    def __init__(self, filename):
        self.zfile = zipfile.ZipFile(filename, 'r')
        self.io_open = io.open

    def names(self):
        return self.zfile.namelist()

    def open(self, filename, mode='r', encoding='utf-8', errors=None):
        filename = filename.replace('\\', '/').replace('./', '')
        if not os.path.isabs(filename):
            try:
                output = with_decoding(StringIO(self.zfile.read(filename).decode(encoding)), None)
                return output
            except KeyError:
                raise IOError('Not found in archive: {}'.format(filename))
        else:
            return self.io_open(filename, mode=mode, encoding=encoding)

    def close(self):
        self.zfile.close()


def extract_metadata(dist, origin=None):
    """"""
    if dist.lower().endswith('.whl'):
        result = _fetch_from_wheel(dist)
    elif dist.lower().endswith('.zip'):
        result = _fetch_from_source(dist, ZipExtractor)
    else:
        extractor_type = NonExtractor
        if dist.lower().endswith('.tar.gz'):
            extractor_type = TarExtractor
        if USE_PROCESS:
            import multiprocessing
            pool = multiprocessing.Pool(processes=1)
            result = pool.apply(_fetch_from_source, args=(os.path.abspath(dist), extractor_type))
            pool.terminate()
            pool.close()
        else:
            result = _fetch_from_source(os.path.abspath(dist), extractor_type)
    if result is not None:
        result.origin = origin
    return result


def _fetch_from_source(source_file, extractor_type):
    """

    Args:
        source_file (str): Source file
        extractor_type (type[Extractor]): Type of extractor to use

    Returns:

    """
    extractor = extractor_type(source_file)  # type: Extractor
    with closing(extractor):
        filename = os.path.basename(source_file)
        name, version = parse_source_filename(filename)
        metadata_file = None
        pkg_info_file = None
        egg_info = None
        setup_file = None

        for info_name in extractor.names():
            if info_name.lower().endswith('pkg-info') and info_name.count('/') <= 1:
                pkg_info_file = info_name
            elif info_name.endswith('.egg-info/requires.txt'):
                egg_info = info_name
            elif info_name.endswith('metadata') and info_name.count('/') <= 1:
                metadata_file = info_name

            if info_name.endswith('setup.py') and info_name.count('/') <= 1:
                setup_file = info_name
                break

        results = None
        if egg_info:
            requires_contents = ''
            try:
                requires_contents = extractor.open(egg_info, encoding='utf-8').read()
            except KeyError:
                pass
            return _parse_requires_file(requires_contents,
                                        name,
                                        version)

        if pkg_info_file:
            results = _parse_flat_metadata(extractor.open(pkg_info_file, encoding='utf-8').read())

        if (results is None or not results.reqs) and setup_file:
            if isinstance(extractor, NonExtractor):
                fake_setupdir = source_file
            else:
                fake_setupdir = tempfile.mkdtemp()
            setup_results = _parse_setup_py(name, version, fake_setupdir,
                                            extractor.relative_opener(fake_setupdir,
                                                                      os.path.dirname(setup_file)))
            if setup_results is not None:
                if version is not None:
                    setup_results.version = version
                if setup_results.name is None:
                    setup_results.name = name
                if results:
                    setup_results.version = results.version
                return setup_results
            elif results is not None:
                return results
            else:
                return None

        if metadata_file:
            return _parse_flat_metadata(extractor.open(metadata_file, encoding='utf-8').read())


def _fetch_from_wheel(wheel):
    zfile = zipfile.ZipFile(wheel, 'r')
    try:
        metadata_file = None
        infos = zfile.namelist()
        for info in infos:
            if info.lower().endswith('metadata'):
                metadata_file = info

        if metadata_file:
            return _parse_flat_metadata(zfile.read(metadata_file).decode('utf-8'))
    finally:
        zfile.close()


def _parse_flat_metadata(contents):
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

    return DistInfo(name, version, list(utils.parse_requirements(raw_reqs)))


class with_decoding(object):
    def __init__(self, wrap, encoding):
        self.file = wrap
        self.encoding = encoding

    def read(self):
        results = self.file.read()
        if self.encoding:
            results = results.decode(self.encoding)
        if six.PY2:
            results = str(''.join([i if ord(i) < 128 else ' ' for i in results]))
        return results

    def readlines(self):
        results = self.file.readlines()
        if self.encoding:
            results = [result.decode(self.encoding) for result in results]
        return results

    def write(self, *args, **kwargs):
        pass

    def __iter__(self):
        if self.encoding:
            return (line.decode(self.encoding) for line in self.file)
        return iter(self.file)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def close(self):
        pass


def setup(results, *args, **kwargs):
    name = kwargs.get('name', None)
    version = kwargs.get('version', '0.0.0')
    reqs = kwargs.get('install_requires', [])
    extra_reqs = kwargs.get('extra_requires', {})

    if version is None or isinstance(version, FakeModule):
        version = '0.0.0'

    if version is not None and version != '':
        version = pkg_resources.parse_version(str(version))

    all_reqs = list(utils.parse_requirements(reqs))
    for extra, extra_req_strs in extra_reqs.items():
        cur_reqs = [utils.parse_requirement('{} ; extra=="{}"'.format(reqstr.strip(), extra))
                    for reqstr in extra_req_strs if reqstr.strip()]
        all_reqs.extend(cur_req for cur_req in cur_reqs if cur_req is not None)

    results.append(DistInfo(name, version, all_reqs))
    return FakeModule('dist')


class FakeModule(types.ModuleType):
    call_count = 0

    def __getitem__(self, item):
        self.call_count += 1
        if self.call_count > 30:
            raise ValueError('Unintended overflow')
        return None

    def __contains__(self, item):
        return True

    def __call__(self, *args, **kwargs):
        return FakeModule(self.__name__)

    def __setitem__(self, key, value):
        pass

    def __getattr__(self, item):
        if isinstance(item, str):
            if item == '__path__':
                return ''
            elif item == '__file__':
                return os.path.join(self.__getattribute__('__name__'), '__init__.py')
            return FakeModule(item)
        else:
            return None


def fake_import_impl(name, orig_import, modname, globals=None, locals=None, fromlist=(), level=0):
    try:
        lower_modname = modname.lower()
        if ('build_ext' in modname) or (fromlist and ('build_ext' in fromlist)):
            raise ImportError()

        if (name == lower_modname or (name + '_') in lower_modname or
                ('_' + name) in lower_modname):
            sys.modules[modname] = FakeModule(modname)
        result = orig_import(modname, globals, locals, fromlist, level)
        return result
    except ImportError as ex:
        # Skip any cython importing to improve setup.py compatibility (e.g. subprocess32)
        if 'Cython' in modname:
            raise
        modparts = modname.split('.')
        if six.PY2:
            for part in modparts:
                if part in PY2_BLACKLIST:
                    raise
        if (name in modname.lower() or
                '_version' in modname or
                'version' in modname or
                modname.startswith('_')):
            for idx, mod in enumerate(modparts):
                sys.modules['.'.join(modparts[:idx + 1])] = FakeModule(mod)
            return FakeModule(modparts[-1])
        try:
            return orig_import(modname, globals, locals, fromlist, level)
        except TypeError:
            raise ImportError
        except ImportError:
            raise
    except SyntaxError:
        print('SyntaxError')
        return FakeModule(modname)
    except (KeyError, TypeError) as ex:
        print('SyntaxError {}'.format(ex))
        return FakeModule(modname)


@contextlib.contextmanager
def patch(module, member, new_value):
    if isinstance(module, str):
        if module not in sys.modules:
            yield
            return

        module = sys.modules[module]

    if not hasattr(module, member):
        old_member = None
    else:
        old_member = getattr(module, member)
    setattr(module, member, new_value)
    try:
        yield
    finally:
        if old_member is None:
            delattr(module, member)
        else:
            setattr(module, member, old_member)


def _remove_encoding_lines(contents):
    lines = contents.split('\n')
    lines = [line for line in lines if not (line.startswith('#') and
                                            ('-*- coding' in line or '-*- encoding' in line or 'encoding:' in line))]
    return '\n'.join(lines)


def _parse_setup_py(name, version, fake_setupdir, opener):

    old_modules = sys.modules.copy()

    # Capture warnings.warn, which is sometimes used in setup.py files
    logging.captureWarnings(True)

    results = []
    setup_with_results = functools.partial(setup, results)

    fake_import = functools.partial(fake_import_impl, name.lower(), __import__)

    import codecs
    import setuptools
    import distutils.core
    import setuptools.extension

    with patch(sys, 'exit', lambda code: None), \
         patch(sys, 'getwindowsversion', lambda: (6, 0, 1)), \
         patch(sys, 'stdout', StringIO()), \
         patch(sys, 'stderr', StringIO()), \
         patch('__builtin__', '__import__', fake_import), \
         patch('builtins', '__import__', fake_import), \
         patch(os, 'listdir', lambda path: []), \
         patch(os, 'getcwd', lambda: '.'), \
         patch(io, 'open', opener), \
         patch(codecs, 'open', opener), \
         patch(imp, 'load_source', lambda *args, **kwargs: FakeModule('load_source')), \
         patch(setuptools, 'setup', setup_with_results), \
         patch(distutils.core, 'setup', setup_with_results):

        spy_globals = {'__file__': os.path.join(fake_setupdir, 'setup.py'),
                       '__name__': '__main__',
                       'open': opener,
                       'setup': setup_with_results}

        contents = opener('setup.py', encoding='utf-8').read()
        try:
            if six.PY2:
                contents = _remove_encoding_lines(contents)
            contents = contents.replace('print ', '')
            exec (contents, spy_globals, spy_globals)
        except Exception as ex:
             raise MetadataError(name, version, ex)
        finally:
            # Restore the old module cache
            modules_to_del = set()
            for module in sys.modules:
                if module not in old_modules:
                    modules_to_del.add(module)

            for module in modules_to_del:
                del sys.modules[module]

    if not results:
        return None
    return results[0]


def _parse_requires_file(contents, name, version):
    reqs = []
    sections = list(pkg_resources.split_sections(contents))
    for section in sections:
        if section[0] is None:
            reqs.extend(utils.parse_requirements(section[1]))
        elif section[0].startswith(':python_version'):
            for req in section[1]:
                reqs.append(utils.parse_requirement(req + ' ' + section[0].replace(':', ';')))

    return DistInfo(name, version, reqs)
