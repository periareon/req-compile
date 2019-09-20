from __future__ import print_function

import contextlib
from contextlib import closing
import shutil
import subprocess
import imp
import io
import logging
import os
import sys
import tarfile
import tempfile
import zipfile
import functools
from types import ModuleType

import six
from six.moves import StringIO
import pkg_resources

from req_compile import utils
from req_compile.dists import DistInfo
from req_compile.importhook import import_hook, import_contents, remove_encoding_lines

LOG = logging.getLogger('req_compile.metadata')


class MetadataError(Exception):
    def __init__(self, name, version, ex):
        super(MetadataError, self).__init__()
        self.name = name
        self.version = version
        self.ex = ex

    def __str__(self):
        return 'Failed to parse metadata for package {} ({}) - {}: {}'.format(
            self.name, self.version, self.ex.__class__.__name__, str(self.ex))


class Extractor(object):
    def names(self):
        pass

    def open(self, filename, mode='r', encoding=None, errors=None, buffering=False, newline=False):
        pass

    def close(self):
        pass

    def relative_opener(self, fake_root, directory):
        def inner_opener(filename, *args, **kwargs):
            archive_path = filename
            if isinstance(filename, int):
                return self.open(filename, *args, **kwargs)
            if os.path.isabs(filename):
                if filename.startswith(fake_root):
                    archive_path = os.path.relpath(filename, fake_root)
                else:
                    return self.open(filename, *args, **kwargs)
            else:
                cur = os.getcwd()
                if cur != fake_root:
                    archive_path = os.path.relpath(cur, fake_root) + '/' + archive_path

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
        for root, _, files in os.walk(self.path):
            rel_root = os.path.relpath(root, parent_dir).replace('\\', '/')
            for filename in files:
                yield rel_root + '/' + filename

    def open(self, filename, mode='r', encoding='utf-8', errors=None, buffering=False, newline=False):
        if not os.path.isabs(filename):
            parent_dir = os.path.abspath(os.path.join(self.path, '..'))
            return self.io_open(os.path.join(parent_dir, filename), mode=mode, encoding=encoding)
        if 'b' in mode:
            return self.io_open(filename, mode=mode)
        return self.io_open(filename, mode=mode, encoding=encoding)

    def close(self):
        pass


class TarExtractor(Extractor):
    def __init__(self, filename):
        self.tar = tarfile.open(filename, 'r:gz')
        self.io_open = io.open

    def names(self):
        return (info.name for info in self.tar.getmembers())

    def open(self, filename, mode='r', encoding='utf-8', errors=None, buffering=False, newline=False):
        if isinstance(filename, int):
            return self.io_open(filename, mode=mode, encoding=encoding)
        filename = filename.replace('\\', '/').replace('./', '')
        if not os.path.isabs(filename):
            try:
                handle = self.tar.extractfile(filename)
                return WithDecoding(handle, encoding=encoding if mode != 'rb' else None)
            except KeyError:
                raise IOError('Not found in archive: {}'.format(filename))
        else:
            kwargs = {}
            if 'b' not in mode:
                kwargs = {'encoding': encoding}
            return self.io_open(filename, mode=mode, **kwargs)

    def close(self):
        self.tar.close()


class ZipExtractor(Extractor):
    def __init__(self, filename):
        self.zfile = zipfile.ZipFile(os.path.abspath(filename), 'r')
        self.io_open = io.open

    def names(self):
        return self.zfile.namelist()

    def open(self, filename, mode='r', encoding='utf-8', errors=None, buffering=False, newline=False):
        if isinstance(filename, int):
            return self.io_open(filename, mode=mode, encoding=encoding)
        filename = filename.replace('\\', '/').replace('./', '')
        if not os.path.isabs(filename):
            try:
                output = WithDecoding(StringIO(self.zfile.read(filename).decode(encoding)), None)
                return output
            except KeyError:
                raise IOError('Not found in archive: {}'.format(filename))
        else:
            kwargs = {}
            if 'b' not in mode:
                kwargs = {'encoding': encoding}
            return self.io_open(filename, mode=mode, **kwargs)

    def close(self):
        self.zfile.close()


def extract_metadata(filename, origin=None):
    """Extract a DistInfo from a file or directory

    Args:
        filename (str): File or path to extract metadata from
        origin (str, req_compile.repos.Repository: Origin of the metadata

    Returns:
        (RequirementContainer) the result of the metadata extraction
    """
    LOG.info('Extracting metadata for %s', filename)
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    if ext == '.whl':
        LOG.debug('Extracting from wheel')
        try:
            result = _fetch_from_wheel(filename)
        except zipfile.BadZipfile as ex:
            raise MetadataError(os.path.basename(filename).replace('.whl', ''), '0.0', ex)
    elif ext == '.zip':
        LOG.debug('Extracting from a zipped source package')
        result = _fetch_from_source(filename, ZipExtractor)
    elif ext in ('.gz', '.tgz'):
        LOG.debug('Extracting from a tar gz package')
        result = _fetch_from_source(os.path.abspath(filename), TarExtractor)
    else:
        LOG.debug('Extracting directly from a source directory')
        result = _fetch_from_source(os.path.abspath(filename), NonExtractor)

    if result is not None:
        result.origin = origin
    return result


def _fetch_from_source(source_file, extractor_type):  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
    """

    Args:
        source_file (str): Source file
        extractor_type (type[Extractor]): Type of extractor to use

    Returns:

    """
    if not os.path.exists(source_file):
        raise ValueError('Source file/path {} does not exist'.format(source_file))

    filename = os.path.basename(source_file)
    name, _ = parse_source_filename(filename)

    if extractor_type is NonExtractor:
        fake_setupdir = source_file
    else:
        fake_setupdir = tempfile.mkdtemp()
        if six.PY2:
            os.mkdir(os.path.join(fake_setupdir, name))

    extractor = extractor_type(source_file)
    with closing(extractor):
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

            if setup_file is None and info_name.endswith('setup.py') and info_name.count('/') <= 1:
                setup_file = info_name
                if extractor_type is NonExtractor:
                    break

        results = None

        if pkg_info_file:
            results = _parse_flat_metadata(extractor.open(pkg_info_file, encoding='utf-8').read())
        elif metadata_file:
            results = _parse_flat_metadata(extractor.open(metadata_file, encoding='utf-8').read())

        # If no metadata exists or the resulting requirements from parsing metadata was empty,
        # re-parse using setup.py.  Some projects don't produce valid source distributions
        if results is None or not results.reqs:
            if setup_file is None:
                raise ValueError('Could not find a setup.py in {}'.format(os.path.basename(source_file)))

            # Attempt a set of executions to obtain metadata from the setup.py without having to build
            # a wheel.  First attempt without mocking __import__ at all. This means that projects
            # which import a package inside of themselves will not succeed, but all other simple
            # source distributions will. If this fails, allow mocking of __import__ to extract from
            # tar files and zip files.  Imports will trigger files to be extracted an executed.  If
            # this fails, due to true build prerequisites not being satisfied or the mocks being
            # insufficient, build the wheel and extract the metadata from it.
            try:
                opener = extractor.relative_opener(fake_setupdir, os.path.dirname(setup_file))
                results = _parse_setup_py(name, fake_setupdir, opener, False)
            except Exception:  # pylint: disable=broad-except
                LOG.warning('Failed to parse %s without import mocks', name, exc_info=True)
                try:
                    results = _parse_setup_py(name, fake_setupdir, opener, True)
                except Exception:  # pylint: disable=broad-except
                    LOG.warning('Failed to parse %s with import mocks', name, exc_info=True)

                    temp_wheeldir = tempfile.mkdtemp()
                    LOG.info('Building wheel file for %s', source_file)
                    try:
                        subprocess.check_output([
                            sys.executable,
                            '-m', 'pip', 'wheel',
                            source_file, '--no-deps', '--wheel-dir', temp_wheeldir
                        ], stderr=subprocess.STDOUT, universal_newlines=True)
                        wheel_file = os.path.join(temp_wheeldir, os.listdir(temp_wheeldir)[0])
                        results = _fetch_from_wheel(wheel_file)
                    except subprocess.CalledProcessError as ex:
                        raise MetadataError(name, None, ValueError(
                            'Pip wheel exited with code {}:\n'.format(ex.returncode) + ex.output))
                    finally:
                        shutil.rmtree(temp_wheeldir)
        elif egg_info:
            requires_contents = ''
            try:
                requires_contents = extractor.open(egg_info, encoding='utf-8').read()
            except KeyError:
                pass
            results = _parse_requires_file(requires_contents,
                                           results.name,
                                           results.version)
        return results


def _fetch_from_wheel(wheel):
    zfile = zipfile.ZipFile(wheel, 'r')
    try:
        metadata_file = None
        infos = zfile.namelist()
        for info in infos:
            if info.lower().endswith('metadata') and info.count('/') <= 1:
                metadata_file = info

        if metadata_file:
            return _parse_flat_metadata(zfile.read(metadata_file).decode('utf-8'))

        return None
    finally:
        zfile.close()


def _parse_flat_metadata(contents):
    name = None
    version = None
    raw_reqs = []

    for line in contents.split('\n'):
        if not line.strip():
            break

        if line.lower().startswith('name:'):
            name = line.split(':')[1].strip()
        if line.lower().startswith('version:'):
            version = utils.parse_version(line.split(':')[1].strip())
        if line.lower().startswith('requires-dist:'):
            raw_reqs.append(line.split(':')[1].strip())

    return DistInfo(name, version, list(utils.parse_requirements(raw_reqs)))


class WithDecoding(object):
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

    def readline(self):
        results = self.file.readline()
        if self.encoding:
            results = results.decode(self.encoding)
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


def setup(results, *_, **kwargs):
    name = kwargs.get('name', None)
    version = kwargs.get('version', '0.0.0')
    reqs = kwargs.get('install_requires', [])
    extra_reqs = kwargs.get('extras_require', {})

    if version is None:
        version = '0.0.0'

    if version is not None and version != '':
        version = pkg_resources.parse_version(str(version))

    if isinstance(reqs, str):
        reqs = [reqs]
    all_reqs = list(utils.parse_requirements(reqs))
    for extra, extra_req_strs in extra_reqs.items():
        try:
            if isinstance(extra_req_strs, six.string_types):
                extra_req_strs = [extra_req_strs]
            cur_reqs = utils.parse_requirements(extra_req_strs)
            reqs_with_extra_marker = [
                utils.parse_requirement(str(cur_req) + ' and extra=="{}"'.format(extra) if ';' in str(cur_req) else
                                        str(cur_req) + '; extra=="{}"'.format(extra))
                for cur_req in cur_reqs]
            all_reqs.extend(reqs_with_extra_marker)
        except pkg_resources.RequirementParseError as ex:
            print('Failed to parse extra requirement ({}) '
                  'from the set:\n{}'.format(str(ex), extra_reqs), file=sys.stderr)
            raise

    results.append(DistInfo(name, version, all_reqs))

    class FakeResult(object):
        def __getattr__(self, item):
            return None
    return FakeResult()


def begin_patch(module, member, new_value):

    if isinstance(module, str):
        if module not in sys.modules:
            return None

        module = sys.modules[module]

    if not hasattr(module, member):
        old_member = None
    else:
        old_member = getattr(module, member)
    setattr(module, member, new_value)
    return module, member, old_member


def end_patch(token):
    if token is None:
        return

    module, member, old_member = token
    if old_member is None:
        delattr(module, member)
    else:
        setattr(module, member, old_member)


@contextlib.contextmanager
def patch(module, member, new_value, conditional=True):
    if not conditional:
        yield
        return

    token = begin_patch(module, member, new_value)
    try:
        yield
    finally:
        end_patch(token)


def get_include():
    return ''


class FakeNumpyModule(ModuleType):
    def __init__(self, name):
        ModuleType.__init__(self, name)  # pylint: disable=non-parent-init-called,no-member

        self.get_include = get_include


class FakeCython(ModuleType):
    def __init__(self, name):
        ModuleType.__init__(self, name)  # pylint: disable=non-parent-init-called,no-member

    def __call__(self, *args, **kwargs):
        return None

    def __iter__(self):
        return iter([])

    def __getattr__(self, item):
        if item == '__path__':
            return []
        return FakeCython(item)


# pylint: disable=too-many-branches
def _parse_setup_py(name, fake_setupdir, opener, mock_import):  # pylint: disable=too-many-locals,too-many-statements
    # pylint: disable=no-name-in-module,no-member
    # Capture warnings.warn, which is sometimes used in setup.py files

    logging.captureWarnings(True)

    results = []
    setup_with_results = functools.partial(setup, results)

    import os.path  # pylint: disable=redefined-outer-name

    spy_globals = {'__file__': os.path.join(fake_setupdir, 'setup.py'),
                   '__name__': '__main__',
                   'setup': setup_with_results}

    # pylint: disable=unused-import,unused-variable
    import codecs
    import distutils.core
    import setuptools.extension
    import setuptools.command.sdist
    import setuptools.command.test
    import setuptools.extern  # Extern performs some weird module manipulation we can't handle
    try:
        import importlib.util
    except ImportError:
        pass

    if 'numpy' not in sys.modules:
        sys.modules['numpy'] = FakeNumpyModule('numpy')

    old_dir = os.getcwd()

    def _fake_exists(path):
        try:
            file_handle = opener(path, 'r')
            file_handle.close()
            return True
        except IOError:
            return False

    os.chdir(fake_setupdir)
    orig_chdir = os.chdir

    def _fake_chdir(new_dir):
        if os.path.isabs(new_dir):
            new_dir = os.path.relpath(new_dir, fake_setupdir)
            if new_dir != '.' and new_dir.startswith('.'):
                raise ValueError('Cannot operate outside of setup dir ({})'.format(new_dir))
        try:
            os.mkdir(new_dir)
        except OSError:
            pass
        return orig_chdir(new_dir)

    old_cythonize = None
    try:
        import Cython.Build
        old_cythonize = Cython.Build.cythonize
        Cython.Build.cythonize = lambda *args, **kwargs: ''
    except ImportError:
        sys.modules['Cython'] = FakeCython('Cython')
        sys.modules['Cython.Build'] = FakeCython('Build')

    if mock_import:
        fake_import = functools.partial(import_hook, opener)

        class FakeSpec(object):  # pylint: disable=too-many-instance-attributes
            class Loader(object):
                def exec_module(self, module):
                    pass

            def __init__(self, modname, path):
                self.loader = FakeSpec.Loader()
                self.name = modname
                self.path = path
                self.submodule_search_locations = None
                self.has_location = True
                self.origin = path
                self.cached = False
                self.parent = None
                self.loader = None

                with opener(path) as handle:
                    self.contents = handle.read()

        # pylint: disable=unused-argument
        def fake_load_source(modname, filename, filehandle=None):
            with opener(filename) as handle:
                return import_contents(modname, filename, handle.read())

        def fake_spec_from_file_location(modname, path, submodule_search_locations=None):
            return FakeSpec(modname, path)

        def fake_module_from_spec(spec):
            return import_contents(spec.name, spec.path, spec.contents)

        spec_from_file_location_patch = begin_patch('importlib.util',
                                                    'spec_from_file_location', fake_spec_from_file_location)
        module_from_spec_patch = begin_patch('importlib.util',
                                             'module_from_spec', fake_module_from_spec)
        py2_import = begin_patch('builtins', '__import__', fake_import)
        py3_import = begin_patch('__builtin__', '__import__', fake_import)
        load_source_patch = begin_patch(imp, 'load_source', fake_load_source)

    with \
         patch(sys, 'exit', lambda code: None), \
         patch(sys, 'stderr', StringIO()), \
         patch(sys, 'stdout', StringIO()), \
         patch('builtins', 'open', opener), \
         patch('__builtin__', 'open', opener), \
         patch('__builtin__', 'execfile', lambda filename: None), \
         patch(os, 'listdir', lambda path: []), \
         patch(os.path, 'exists', _fake_exists), \
         patch(os, 'chdir', _fake_chdir), \
         patch(io, 'open', opener), \
         patch(codecs, 'open', opener), \
         patch(setuptools, 'setup', setup_with_results), \
         patch(distutils.core, 'setup', setup_with_results):

        contents = opener('setup.py', encoding='utf-8').read()
        try:
            if six.PY2:
                contents = remove_encoding_lines(contents)

            sys.path.insert(0, fake_setupdir)
            # pylint: disable=exec-used
            contents = contents.replace('print ', '')
            exec(contents, spy_globals, spy_globals)
        finally:
            orig_chdir(old_dir)
            if old_cythonize is not None:
                Cython.Build.cythonize = old_cythonize
            sys.path.remove(fake_setupdir)

            if mock_import:
                end_patch(load_source_patch)
                end_patch(spec_from_file_location_patch)
                end_patch(module_from_spec_patch)
                end_patch(py2_import)
                end_patch(py3_import)

            for module in list(sys.modules.keys()):
                if isinstance(module, (FakeCython, FakeNumpyModule)):
                    del sys.modules[module]
            if 'versioneer' in sys.modules:
                del sys.modules['versioneer']

    if not results:
        raise ValueError('Distutils/setuptools setup() was not ever '
                         'called on "{}". Is this a valid project?'.format(name))
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
