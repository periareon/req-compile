"""Extractors for Python distribution archive types"""
from __future__ import annotations

import abc
import codecs
import io
import logging
import os
import shutil
import tarfile
import zipfile
from io import BytesIO
from types import TracebackType
from typing import IO, Any, Dict, Iterable, Iterator, List, Optional, Type, Union, cast

from typing_extensions import Literal

LOG = logging.getLogger("req_compile.extractor")


class Extractor(metaclass=abc.ABCMeta):
    """Abstract base class for file extractors. These classes operate on archive files
    or directories in order to expose files to metadata analysis and executing setup.pys.
    """

    def __init__(self, extractor_type: str, file_or_path: str) -> None:
        self.logger = LOG.getChild(extractor_type)
        self.fake_root: str = os.path.abspath(os.sep + os.path.basename(file_or_path))
        self.io_open = io.open
        self.renames: Dict[Union[str, int], Union[str, int]] = {}

    def contains_path(self, path: str) -> bool:
        """Whether or not the archive contains the given path, based on the fake root.
        Returns:
            (bool)
        """
        return os.path.abspath(path).startswith(self.fake_root)

    def add_rename(self, name: str, new_name: str) -> None:
        """Add a rename entry for a file in the archive"""
        self.renames[self.to_relative(new_name)] = self.to_relative(name)

    def open(
        self, file: str, mode: str = "r", encoding: str = None, **_kwargs: Any
    ) -> IO[str]:
        """Open a real file or a file within the archive"""
        relative_filename = self.to_relative(file)
        if (
            isinstance(relative_filename, int)
            or file == os.devnull
            or os.path.isabs(relative_filename)
        ):
            return self.io_open(file, mode=mode, encoding=encoding)

        handle = self._open_handle(relative_filename)
        if "b" in mode:
            return handle

        return cast(IO[str], WithDecoding(handle, encoding or "ascii"))

    @abc.abstractmethod
    def names(self) -> Iterable[str]:
        """Fetch all names within the archive

        Returns:
            (generator[str]): Filenames, in the context of the archive
        """
        raise NotImplementedError

    @abc.abstractmethod
    def _open_handle(self, filename: str) -> Any:
        raise NotImplementedError

    @abc.abstractmethod
    def _check_exists(self, filename: str) -> bool:
        raise NotImplementedError

    def exists(self, filename: Union[str, int]) -> bool:
        """Check whether a file or directory exists within the archive.
        Will not check non-archive files"""
        relative_fd = self.to_relative(filename)
        if isinstance(relative_fd, int):
            return os.path.exists(filename)

        return self._check_exists(relative_fd)

    def close(self) -> None:
        raise NotImplementedError

    def to_relative(self, filename: Union[str, int]) -> Union[str, int]:
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

        mapped_result: Union[str, int] = result
        if result in self.renames:
            mapped_result = self.renames[result]
        return mapped_result

    def contents(self, name: str) -> str:
        """Read the full contents of a file opened with Extractor.open

        Returns:
            (str) The full file contents
        """
        with self.open(name, encoding="utf-8") as handle:
            return handle.read()

    @abc.abstractmethod
    def extract(self, target_dir: str) -> None:
        raise NotImplementedError


class NonExtractor(Extractor):
    """An extractor that operates on the filesystem directory instead of an archive"""

    def __init__(self, path: str) -> None:
        super(NonExtractor, self).__init__("fs", path)
        self.path = path
        self.os_path_exists = os.path.exists

    def names(self) -> Iterable[str]:
        for root, _, files in os.walk(self.path):
            rel_root = root.replace(self.path, ".").replace("\\", "/")
            if rel_root != ".":
                rel_root += "/"
            else:
                rel_root = ""
            for filename in files:
                yield rel_root + filename

    def extract(self, target_dir: str) -> None:
        # Copy the entire file tree to the target directory
        os.rmdir(target_dir)
        shutil.copytree(self.path, target_dir, ignore=shutil.ignore_patterns(".git"))

    def _check_exists(self, filename: str) -> bool:
        return self.os_path_exists(self.path + "/" + filename)

    def _open_handle(self, filename: str) -> IO[bytes]:
        return self.io_open(os.path.join(self.path, filename), "rb")

    def close(self) -> None:
        pass


class TarExtractor(Extractor):
    """An extractor for tar files. Accepts an additional first parameter for the decoding codec"""

    def __init__(self, ext: Literal["gz"], filename: str):
        super(TarExtractor, self).__init__("tar", filename)
        self.tar = tarfile.open(filename, "r:" + ext)
        self.io_open = io.open

    def names(self) -> Iterable[str]:
        return (info.name for info in self.tar.getmembers() if info.type != b"5")

    def _check_exists(self, filename: str) -> bool:
        try:
            self.tar.getmember(filename)
            return True
        except KeyError:
            return False

    def extract(self, target_dir: str) -> None:
        self.tar.extractall(path=target_dir)

    def _open_handle(self, filename: str) -> Any:
        try:
            return self.tar.extractfile(filename)
        except KeyError:
            raise IOError("Could not find {}".format(filename))

    def close(self) -> None:
        self.tar.close()


class ZipExtractor(Extractor):
    """An extractor for zip files"""

    def __init__(self, filename: str) -> None:
        super(ZipExtractor, self).__init__("gz", filename)
        self.zfile = zipfile.ZipFile(os.path.abspath(filename), "r")
        self.io_open = io.open

    def names(self) -> Iterable[str]:
        return (name for name in self.zfile.namelist() if name[-1] != "/")

    def _check_exists(self, filename: str) -> bool:
        try:
            self.zfile.getinfo(filename)
            return True
        except KeyError:
            return any(name.startswith(filename + "/") for name in self.names())

    def extract(self, target_dir: str) -> None:
        self.zfile.extractall(path=target_dir)

    def _open_handle(self, filename: str) -> Any:
        try:
            return BytesIO(self.zfile.read(filename))
        except KeyError:
            raise IOError("Could not find {}".format(filename))

    def close(self) -> None:
        self.zfile.close()


class WithDecoding:
    """Wrap a file object and handle decoding."""

    def __init__(self, wrap: IO[bytes], encoding: str) -> None:
        super().__init__()
        if wrap is None:
            raise FileNotFoundError

        self.wrap = wrap
        self.reader = codecs.getreader(encoding)(wrap)

    def read(self, __n: int = 1024 * 1024) -> str:
        return self.reader.read(__n)

    def readline(self, __limit: int = None) -> str:
        return self.reader.readline(__limit)

    def readlines(self, __hint: int = None) -> List[str]:
        return self.reader.readlines(__hint)

    def write(self, data: Any) -> int:
        del data
        return 0

    def __getattr__(self, item: str) -> Any:
        return getattr(self.wrap, item)

    def __iter__(self) -> Iterator[str]:
        return iter(self.reader)

    def __next__(self) -> str:
        return next(self.reader)

    def __enter__(self) -> WithDecoding:
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        pass

    def close(self) -> None:
        self.wrap.close()
