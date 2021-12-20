"""PEP517 pyproject.toml support. One major restriction: build isolation is not supported"""
import importlib
import logging
import os
import shutil
import sys
import tempfile
import threading
from typing import Any, Mapping, Optional

import toml
from six.moves import StringIO

from ..containers import DistInfo
from .dist_info import _fetch_from_wheel, _parse_flat_metadata
from .patch import patch

LOG = logging.getLogger("req_compile.metadata.source")
LOCK = threading.Lock()


def _create_build_backend(build_system):
    # type: (Mapping) -> Any
    backend_name = build_system["build-backend"]
    module, _, obj = backend_name.partition(":")
    backend = importlib.import_module(module)
    if obj:
        backend = getattr(backend, obj)
    return backend


def _parse_from_prepared_metadata(source_file, backend, pyproject):
    # type: (str, Any, Mapping) -> Optional[DistInfo]
    prepare = getattr(backend, "prepare_metadata_for_build_wheel", None)
    if prepare is None:
        return None

    dest = tempfile.mkdtemp(suffix="metadata")
    try:
        try:
            info = prepare(dest, proj=pyproject, cwd=source_file)
        except TypeError:
            # We can only manipulate the working dir one at a time
            with LOCK:
                old_cwd = os.getcwd()
                try:
                    os.chdir(source_file)
                    fake_out = StringIO()
                    with patch(sys, "stdout", fake_out, sys, "stderr", fake_out):
                        info = prepare(dest)
                finally:
                    os.chdir(old_cwd)

        meta_info = os.path.join(dest, info, "METADATA")
        if os.path.exists(meta_info):
            with open(meta_info, "r") as file_handle:
                return _parse_flat_metadata(file_handle.read())
    finally:
        shutil.rmtree(dest)

    return None


def _parse_from_wheel(backend):
    # type: (Mapping[str, Any]) -> Optional[DistInfo]
    build_wheel = getattr(backend, "build_wheel", None)
    if build_wheel is None:
        return None
    dest = tempfile.mkdtemp()
    try:
        wheel = build_wheel(dest)
        return _fetch_from_wheel(os.path.join(dest, wheel))
    finally:
        shutil.rmtree(dest)


def fetch_from_pyproject(source_file):
    # type: (str) -> Optional[DistInfo]
    """Fetch metadata from pyproject.toml either by relying on the backend to provide metadata, or by building
    a wheel and extracting the metadata"""
    try:
        pyproject = toml.load(os.path.join(source_file, "pyproject.toml"))
    except toml.TomlDecodeError as ex:
        LOG.debug("Failed to load pyproject.toml: %s", ex)
        return None

    try:
        build_system = pyproject["build-system"]
        backend = _create_build_backend(build_system)
    except KeyError:
        LOG.debug("No build-system in the pyproject.toml")
        return None
    except ImportError:
        LOG.debug(
            "Could not import backend %s", pyproject["build-system"]["build-backend"]
        )
        return None

    result = _parse_from_prepared_metadata(source_file, backend, pyproject)
    if result is not None:
        return result

    result = _parse_from_wheel(backend)
    return result
