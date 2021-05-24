"""Extractors for Python distribution archive types"""
import io
import logging
import os
import shutil
import tarfile
import zipfile

import six
from six import BytesIO

LOG = logging.getLogger("req_compile.extractor")


class Extractor(object):
    """Abstract base class for file extractors. These classes operate on archive files or directories in order
    to expose files to metadata analysis and executing setup.pys.
    """

    def __init__(self, extractor_type, file_or_path):
        self.logger = LOG.getChild(extractor_type)
        self.fake_root = os.path.abspath(os.sep + os.path.basename(file_or_path))
        self.io_open = io.open
        self.renames = {}

    def contains_path(self, path):
        """Whether or not the archive contains the given path, based on the fake root.
        Returns:
            (bool)
        """
        return os.path.abspath(path).startswith(self.fake_root)

    def add_rename(self, name, new_name):
        """Add a rename entry for a file in the archive"""
        self.renames[self.to_relative(new_name)] = self.to_relative(name)

    def open(self, file, mode="r", encoding=None, **_kwargs):
        """Open a real file or a file within the archive"""
        relative_filename = self.to_relative(file)
        if (
            isinstance(file, int)
            or file == os.devnull
            or os.path.isabs(relative_filename)
        ):
            return self.io_open(file, mode=mode, encoding=encoding)

        kwargs = {}
        if "b" not in mode:
            kwargs = {"encoding": encoding or "ascii"}
        handle = self._open_handle(relative_filename)
        return WithDecoding(handle, **kwargs)

    def names(self):
        """Fetch all names within the archive

        Returns:
            (generator[str]): Filenames, in the context of the archive
        """
        raise NotImplementedError

    def _open_handle(self, filename):
        raise NotImplementedError

    def _check_exists(self, filename):
        raise NotImplementedError

    def exists(self, filename):
        """Check whether a file or directory exists within the archive. Will not check non-archive files"""
        return self._check_exists(self.to_relative(filename))

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

        if filename.replace("\\", "/").startswith("./"):
            filename = filename[2:]
        result = filename
        if os.path.isabs(filename):
            if self.contains_path(filename):
                result = filename.replace(self.fake_root, ".", 1)
        else:
            cur = os.getcwd()
            if cur != self.fake_root:
                result = os.path.relpath(cur, self.fake_root) + "/" + filename

        result = result.replace("\\", "/")
        if result.startswith("./"):
            result = result[2:]

        if result in self.renames:
            result = self.renames[result]
        return result

    def contents(self, name):
        """Read the full contents of a file opened with Extractor.open

        Returns:
            (str) The full file contents
        """
        with self.open(name, encoding="utf-8") as handle:
            return handle.read()


class NonExtractor(Extractor):
    """An extractor that operates on the filesystem directory instead of an archive"""

    def __init__(self, path):
        super(NonExtractor, self).__init__("fs", path)
        self.path = path
        self.os_path_exists = os.path.exists

    def names(self):
        for root, _, files in os.walk(self.path):
            rel_root = root.replace(self.path, ".").replace("\\", "/")
            if rel_root != ".":
                rel_root += "/"
            else:
                rel_root = ""
            for filename in files:
                yield rel_root + filename

    def extract(self, target_dir):
        # Copy the entire file tree to the target directory
        for filename in os.listdir(self.path):
            path = os.path.join(self.path, filename)
            if os.path.isdir(path):
                shutil.copytree(path, os.path.join(target_dir, filename))
            else:
                shutil.copy2(path, target_dir)

    def _check_exists(self, filename):
        return self.os_path_exists(self.path + "/" + filename)

    def _open_handle(self, filename):
        try:
            return self.io_open(os.path.join(self.path, filename), "rb")
        except KeyError:
            raise IOError("Could not find {}".format(filename))

    def close(self):
        pass


class TarExtractor(Extractor):
    """An extractor for tar files. Accepts an additional first parameter for the decoding codec"""

    def __init__(self, ext, filename):
        super(TarExtractor, self).__init__("tar", filename)
        self.tar = tarfile.open(filename, "r:" + ext)
        self.io_open = io.open

    def names(self):
        return (info.name for info in self.tar.getmembers() if info.type != b"5")

    def _check_exists(self, filename):
        try:
            self.tar.getmember(filename)
            return True
        except KeyError:
            return False

    def extract(self, target_dir):
        old_dir = os.getcwd()
        os.chdir(target_dir)
        try:
            self.tar.extractall()
        finally:
            os.chdir(old_dir)

    def _open_handle(self, filename):
        try:
            return self.tar.extractfile(filename)
        except KeyError:
            raise IOError("Could not find {}".format(filename))

    def close(self):
        self.tar.close()


class ZipExtractor(Extractor):
    """An extractor for zip files"""

    def __init__(self, filename):
        super(ZipExtractor, self).__init__("gz", filename)
        self.zfile = zipfile.ZipFile(os.path.abspath(filename), "r")
        self.io_open = io.open

    def names(self):
        return (name for name in self.zfile.namelist() if name[-1] != "/")

    def _check_exists(self, filename):
        try:
            self.zfile.getinfo(filename)
            return True
        except KeyError:
            return any(name.startswith(filename + "/") for name in self.names())

    def extract(self, target_dir):
        old_dir = os.getcwd()
        os.chdir(target_dir)
        try:
            self.zfile.extractall()
        finally:
            os.chdir(old_dir)

    def _open_handle(self, filename):
        try:
            return BytesIO(self.zfile.read(filename))
        except KeyError:
            raise IOError("Could not find {}".format(filename))

    def close(self):
        self.zfile.close()


class WithDecoding(object):
    """Wrap a file object and handle decoding for Python 2 and Python 3"""

    def __init__(self, wrap, encoding=None):
        if wrap is None:
            raise IOError("File not found")
        self.file = wrap
        self.encoding = encoding
        self.iter = iter(self)

    def _do_decode(self, results):
        if six.PY3 and self.encoding and isinstance(results, bytes):
            results = results.decode(self.encoding, "ignore")
        if six.PY2:
            results = str("".join([i if ord(i) < 128 else " " for i in results]))
        return results

    def read(self, nbytes=None):
        results = self.file.read(nbytes)
        return self._do_decode(results)

    def readline(self):
        results = self.file.readline()
        return self._do_decode(results)

    def readlines(self):
        results = self.file.readlines()
        return [self._do_decode(result) for result in results]

    def write(self, *args, **kwargs):
        pass

    def __getattr__(self, item):
        return getattr(self.file, item)

    def __iter__(self):
        if self.encoding:
            return (self._do_decode(line) for line in self.file)
        return iter(self.file)

    def __next__(self):
        return next(self.iter)

    def next(self):
        return next(self.iter)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def close(self):
        pass
