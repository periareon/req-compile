"""Extractors for Python distribution archive types"""
import io
import os
import tarfile
import zipfile

import six
from six import StringIO


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

            return self.open(((directory + '/') if directory else '') + archive_path, *args, **kwargs)
        return inner_opener

    def contents(self, name):
        return self.open(name, encoding='utf-8').read()


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
    def __init__(self, ext, filename):
        self.tar = tarfile.open(filename, 'r:' + ext)
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
                output = WithDecoding(StringIO(self.zfile.read(filename).decode(encoding, errors='ignore')), None)
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


class WithDecoding(object):
    def __init__(self, wrap, encoding):
        if wrap is None:
            raise OSError('File not found: {}'.format(wrap))
        self.file = wrap
        self.encoding = encoding

    def read(self):
        results = self.file.read()
        if self.encoding:
            results = results.decode(self.encoding, 'ignore')
        if six.PY2:
            results = str(''.join([i if ord(i) < 128 else ' ' for i in results]))
        return results

    def readline(self):
        results = self.file.readline()
        if self.encoding:
            results = results.decode(self.encoding, 'ignore')
        return results

    def readlines(self):
        results = self.file.readlines()
        if self.encoding:
            results = [result.decode(self.encoding, 'ignore') for result in results]
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
