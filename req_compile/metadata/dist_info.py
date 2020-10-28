import logging
import os
import re
import zipfile
from contextlib import closing
from typing import Iterable, Optional

from req_compile import utils
from req_compile.containers import DistInfo

LOG = logging.getLogger("req_compile.metadata.dist_info")


def _find_dist_info_metadata(project_name, namelist):
    # type: (str, Iterable[str]) -> Optional[str]
    """
    In a list of zip path entries, find the one that matches the dist-info for this project

    Args:
        project_name (str): Project name to match
        namelist (list[str]): List of zip paths

    Returns:
        (str) The best zip path that matches this project
    """
    for best_match in (
        r"^(.+/)?{}-.+\.dist-info/METADATA$".format(project_name),
        r"^.*\.dist-info/METADATA",
    ):
        for info in namelist:
            if re.match(best_match, info):
                LOG.debug(
                    "Found dist-info in the zip: %s (with regex %s)", info, best_match
                )
                return info

    return None


def _fetch_from_wheel(wheel):
    # type: (str) -> Optional[DistInfo]
    """
    Fetch metadata from a wheel file
    Args:
        wheel (str): Wheel filename

    Returns:
        (DistInfo, None) The metadata for this zip, or None if it could not be found or parsed
    """
    project_name = os.path.basename(wheel).split("-")[0]

    zfile = zipfile.ZipFile(wheel, "r")
    with closing(zfile):
        # Reverse since metadata details are supposed to be written at the end of the zip
        infos = list(reversed(zfile.namelist()))
        result = _find_dist_info_metadata(project_name, infos)
        if result is not None:
            return _parse_flat_metadata(zfile.read(result).decode("utf-8", "ignore"))

        LOG.warning("Could not find .dist-info/METADATA in the zip archive")
        return None


def _parse_flat_metadata(contents):
    name = None
    version = None
    raw_reqs = []

    for line in contents.split("\n"):
        lower_line = line.lower()
        if name is None and lower_line.startswith("name:"):
            name = line.split(":")[1].strip()
        elif version is None and lower_line.startswith("version:"):
            version = utils.parse_version(line.split(":")[1].strip())
        elif lower_line.startswith("requires-dist:"):
            raw_reqs.append(line.partition(":")[2].strip())

    return DistInfo(name, version, list(utils.parse_requirements(raw_reqs)))
