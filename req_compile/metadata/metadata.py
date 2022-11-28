import functools
import logging
import os
import zipfile
from typing import List, Optional

import pkg_resources

from req_compile.containers import RequirementContainer
from req_compile.errors import MetadataError
from req_compile.repos.repository import Repository

from ..utils import parse_version
from .dist_info import _fetch_from_wheel
from .extractor import NonExtractor, TarExtractor, ZipExtractor
from .pyproject import fetch_from_pyproject
from .source import _fetch_from_source

LOG = logging.getLogger("req_compile.metadata")


def extract_metadata(
    filename: str, allow_run_setup_py: bool = True, origin: Repository = None
) -> RequirementContainer:
    """Extract a DistInfo from a file or directory

    Args:
        filename: File or path to extract metadata from
        allow_run_setup_py: Whether this call is permitted to run setup.py files
        origin: Origin of the metadata

    Returns:
        (RequirementContainer) the result of the metadata extraction
    """
    LOG.info("Extracting metadata for %s", filename)
    basename, ext = os.path.splitext(filename)
    result: Optional[RequirementContainer] = None
    ext = ext.lower()

    # Gather setup requires from setup.py and pyproject.toml.
    setup_requires: List[pkg_resources.Requirement] = []

    if ext == ".whl":
        LOG.debug("Extracting from wheel")
        try:
            result = _fetch_from_wheel(filename)
        except zipfile.BadZipfile as ex:
            raise MetadataError(
                os.path.basename(filename).replace(".whl", ""), parse_version("0.0"), ex
            )
    elif ext == ".zip":
        LOG.debug("Extracting from a zipped source package")
        result = _fetch_from_source(
            filename, ZipExtractor, run_setup_py=allow_run_setup_py
        )
    elif ext in (".gz", ".bz2", ".tgz"):
        LOG.debug("Extracting from a tar package")
        if ext == ".tgz":
            ext = "gz"
        result = _fetch_from_source(
            os.path.abspath(filename),
            functools.partial(TarExtractor, ext.replace(".", "")),
            run_setup_py=allow_run_setup_py,
        )
    elif ext in (".egg",):
        LOG.debug("Attempted to resolve an unsupported format")
        raise MetadataError(basename, None, ValueError(".egg files are not supported"))
    elif os.path.exists(os.path.join(filename, "pyproject.toml")):
        LOG.debug("Extracting from a pyproject.toml")
        result, setup_requires = fetch_from_pyproject(filename)

    if result is None:
        LOG.debug("Extracting directly from a source directory")
        result = _fetch_from_source(
            os.path.abspath(filename), NonExtractor, run_setup_py=allow_run_setup_py
        )

    if result is not None:
        result.origin = origin

    if result is None:
        raise MetadataError(basename, None, ValueError("Could not extract metadata"))

    result.setup_reqs.extend(setup_requires)
    return result
