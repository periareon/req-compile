import os
import re

from req_compile import utils


def parse_source_filename(full_filename):
    filename = full_filename.replace(".tar.gz", "")
    filename = filename.replace(".tar.bz2", "")
    filename = filename.replace(".zip", "")
    filename = filename.replace(".tgz", "")

    # Source directories don't express a version
    if full_filename == filename:
        return full_filename, None

    filename = filename.replace("_", "-")

    dash_parts = filename.split("-")
    version_start = None
    for idx, part in enumerate(dash_parts):
        if not part:
            continue
        # pylint: disable=too-many-boolean-expressions
        if (idx != 0 and idx >= len(dash_parts) - 3) and (
            part[0].isdigit()
            or (len(part) > 1 and part[0].lower() == "v" and part[1].isdigit())
        ):
            if (
                idx == len(dash_parts) - 2
                and "." in dash_parts[idx + 1]
                and ("." not in part or re.sub(r"[\d.]+", "", part))
            ):
                continue
            version_start = idx
            break

    if version_start is None:
        return os.path.basename(filename), None

    if version_start == 0:
        raise ValueError("Package name missing: {}".format(full_filename))

    pkg_name = "-".join(dash_parts[:version_start])

    version_str = "-".join(dash_parts[version_start:]).replace("_", "-")
    version_parts = version_str.split(".")
    for idx, part in enumerate(version_parts):
        if idx != 0 and (
            part.startswith("linux")
            or part.startswith("windows")
            or part.startswith("macos")
        ):
            version_parts = version_parts[:idx]
            break

    version = utils.parse_version(".".join(version_parts))
    return pkg_name, version
