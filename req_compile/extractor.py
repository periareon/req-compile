"""Extractors for Python distribution archive types"""
import io
import logging
import os
import tarfile
import zipfile

import six
from six import StringIO

LOG = logging.getLogger('req_compile.extractor')


class Extractor(object):
    """Abstract base class for file extractors. These classes operate on archive files or directories in order
    to expose files to metadata analysis and executing setup.pys.
    """
    def __init__(self, extractor_type, fake_root):
        self.logger = LOG.getChild(extractor_type)
        self.fake_root = fake_root
        self.io_open = io.open

    def contains_path(self, path):
        """Whether or not the archive contains the given path, based on the fake root.
        Returns:
            (bool)
        """
        return os.path.abspath(path).startswith(os.path.abspath(self.fake_root))

    def open(self, filename, mode='r', encoding=None, **_kwargs):
        """Open a real file or a file within the archive"""
        self.logger.debug('Raw %s', filename)
        filename = self.to_relative(filename)
        if isinstance(filename, int) or not self.contains_path(filename):
            return self.io_open(filename, mode=mode, encoding=encoding)

        kwargs = {}
        if 'b' not in mode:
            kwargs = {'encoding': encoding}
        handle = self._open_handle(filename.replace('\\', '/'))
        return WithDecoding(handle, **kwargs)

    def names(self):
        """Fetch all names within the archive

        Returns:
            (generator[str]): Filenames, in the context of the archive
        """
        raise NotImplementedError

    def _open_handle(self, filename):
        raise NotImplementedError

    def exists(self, filename):
        """Check whether a file or directory exists within the archive. Will not check non-archive files"""
        raise NotImplementedError

    def close(self):
        pass

    def to_relative(self, filename):
        """Convert a path to an archive relative path if possible. If the target file is not
        within the archive, the path will be returned as is

        Returns:
            (str) The path to use to open the file or check existence
        """
        if isinstance(filename, int):
            return filename

        result = filename
        if os.path.isabs(filename):
            if self.contains_path(filename):
                result = os.path.relpath(filename, self.fake_root)
        else:
            cur = os.getcwd()
            if cur != self.fake_root:
                result = os.path.relpath(cur, self.fake_root) + '/' + filename

        result = result.replace('\\', '/')
        if result.startswith('./'):
            result = result[2:]
        return result

    def contents(self, name):
        """Read the full contents of a file opened with Extractor.open

        Returns:
            (str) The full file contents
        """
        with self.open(name, encoding='utf-8') as handle:
            return handle.read()


class NonExtractor(Extractor):
    """An extractor that operates on the filesystem directory instead of an archive"""
    def __init__(self, path, root):
        super(NonExtractor, self).__init__('fs', root)
        self.path = path
        self.os_path_exists = os.path.exists

    def names(self):
        for root, _, files in os.walk(self.path):
            rel_root = os.path.relpath(root, self.path).replace('\\', '/')
            if rel_root != '.':
                rel_root += '/'
            else:
                rel_root = ''
            for filename in files:
                yield rel_root + filename

    def exists(self, filename):
        return self.os_path_exists(os.path.join(self.path, self.to_relative(filename)))

    def _open_handle(self, filename):
        try:
            return self.io_open(os.path.join(self.path, filename))
        except KeyError:
            raise IOError('Could not find {}'.format(filename))

    def close(self):
        pass


class TarExtractor(Extractor):
    """An extractor for tar files. Accepts an additional first parameter for the decoding codec"""
    def __init__(self, ext, filename, root):
        super(TarExtractor, self).__init__('tar', root)
        self.tar = tarfile.open(filename, 'r:' + ext)
        self.io_open = io.open

    def names(self):
        return (info.name for info in self.tar.getmembers()
                if info.type != '5')

    def exists(self, filename):
        try:
            self.tar.getmember(self.to_relative(filename))
            return True
        except KeyError:
            return False

    def _open_handle(self, filename):
        try:
            return self.tar.extractfile(filename)
        except KeyError:
            raise IOError('Could not find {}'.format(filename))

    def close(self):
        self.tar.close()


class ZipExtractor(Extractor):
    """An extractor for zip files"""
    def __init__(self, filename, root):
        super(ZipExtractor, self).__init__('gz', root)
        self.zfile = zipfile.ZipFile(os.path.abspath(filename), 'r')
        self.io_open = io.open

    def names(self):
        return (name for name in self.zfile.namelist() if name[-1] != '/')

    def exists(self, filename):
        filename = self.to_relative(filename)
        try:
            self.zfile.getinfo(filename)
            return True
        except KeyError:
            return any(name.startswith(filename + '/') for name in self.names())

    def _open_handle(self, filename):
        try:
            return StringIO(self.zfile.read(filename).decode('utf-8', errors='ignore'))
        except KeyError:
            raise IOError('Could not find {}'.format(filename))

    def close(self):
        self.zfile.close()


class WithDecoding(object):
    """Wrap a file object and handle decoding for Python 2 and Python 3"""
    def __init__(self, wrap, encoding):
        if wrap is None:
            raise OSError('File not found: {}'.format(wrap))
        self.file = wrap
        self.encoding = encoding

    def read(self):
        results = self.file.read()
        if six.PY3 and self.encoding:
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
