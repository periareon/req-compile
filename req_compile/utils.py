import itertools
import os
import logging
from collections import defaultdict

try:
    from functools32 import lru_cache
except ImportError:
    from functools import lru_cache

import pkg_resources


def _req_iter_from_file(reqfile_name):
    with open(reqfile_name, "r") as reqfile:
        for req_line in reqfile:
            req_line = req_line.strip()
            if not req_line:
                continue
            if req_line.startswith("-r"):
                for req in _req_iter_from_file(
                    os.path.join(
                        os.path.dirname(reqfile_name), req_line.split(" ")[1].strip()
                    )
                ):
                    yield req
            elif req_line.startswith("--index-url") or req_line.startswith(
                "--extra-index-url"
            ):
                pass
            elif req_line.startswith("#"):
                pass
            else:
                try:
                    yield parse_requirement(req_line)
                except ValueError:
                    logging.getLogger("req.utils").exception(
                        "Failed to parse %s", req_line
                    )
                    raise


def reqs_from_files(requirements_files):
    """
    Args:
        requirements_files (list[str]): Requirements files
    """
    raw_reqs = iter([])
    for reqfile_name in requirements_files:
        raw_reqs = itertools.chain(raw_reqs, _req_iter_from_file(reqfile_name))

    return list(raw_reqs)


def reduce_requirements(raw_reqs):
    """Reduce a list of requirements to a minimal list by combining requirements with the same key"""
    reqs = defaultdict(lambda: None)
    for req in raw_reqs:
        reqs[req.name] = merge_requirements(reqs[req.name], req)

    return list(reqs.values())


@lru_cache(maxsize=None)
def parse_requirement(req_text):
    """
    Parse a string into a Requirement object

    Args:
        req_text (str): The pkg_resources style requirement string,
            e.g. flask==1.1 ; python_version >= '3.0'

    Returns:
        (pkg_resources.Requirement) The parsed requirement
    """
    req_text = req_text.strip()
    if not req_text:
        return None
    if req_text[0] == "#":
        return None
    return pkg_resources.Requirement.parse(req_text)


@lru_cache(maxsize=None)
def parse_version(version):
    """
    Args:
        version (str): Version to parse
    """
    return pkg_resources.parse_version(version)


def parse_requirements(reqs):
    """Parse a list of strings into a generate of pkg_resources.Requirements"""
    for req in reqs:
        req = req.strip()
        if "\n" in req:
            for inner_req in parse_requirements(req.split("\n")):
                yield inner_req
        else:
            result = parse_requirement(req)
            if result is not None:
                yield result


def merge_extras(extras1, extras2):
    """Merge two iterables of extra into a single sorted tuple. Case-sensitive"""
    if not extras1:
        return extras2
    if not extras2:
        return extras1
    return tuple(sorted(set(extras1) | set(extras2)))


def merge_requirements(req1, req2):
    """Merge two requirements into a single requirement that would satisfy both"""
    if req1 is not None and req2 is None:
        return req1
    if req2 is not None and req1 is None:
        return req2

    req1_name_norm = normalize_project_name(req1.name)
    if req1_name_norm != normalize_project_name(req2.name):
        raise ValueError("Reqs don't match: {} != {}".format(req1, req2))
    all_specs = set(req1.specs or []) | set(req2.specs or [])

    # Handle markers
    if req1.marker and req2.marker:
        if str(req1.marker) != str(req2.marker):
            if str(req1.marker) in str(req2.marker):
                new_marker = ";" + str(req1.marker)
            elif str(req2.marker) in str(req1.marker):
                new_marker = ";" + str(req2.marker)
            else:
                new_marker = ""
        else:
            new_marker = ";" + str(req1.marker)
    else:
        new_marker = ""

    extras = merge_extras(req1.extras, req2.extras)
    extras_str = ""
    if extras:
        extras_str = "[" + ",".join(extras) + "]"
    req_str = (
        req1_name_norm
        + extras_str
        + ",".join("".join(parts) for parts in all_specs)
        + new_marker
    )
    return parse_requirement(req_str)


NAME_CACHE = {}


def normalize_project_name(project_name):
    """Normalize a project name"""
    if project_name in NAME_CACHE:
        return NAME_CACHE[project_name]
    value = project_name.lower().replace("-", "_").replace(".", "_").replace(" ", "_")
    NAME_CACHE[project_name] = value
    return value


def filter_req(req, extra):
    """Apply an extra using a requirements markers and return True if this requirement is kept"""
    if extra and not req.marker:
        return False
    keep_req = True
    if req.marker:
        if not extra:
            extra = None
        keep_req = req.marker.evaluate({"extra": extra})
    return keep_req


def is_pinned_requirement(req):
    """Returns whether an InstallRequirement is a "pinned" requirement.

    An InstallRequirement is considered pinned if:
    - Is not editable
    - It has exactly one specifier
    - That specifier is "=="
    - The version does not contain a wildcard

    Examples:
        django==1.8   # pinned
        django>1.8    # NOT pinned
        django~=1.8   # NOT pinned
        django==1.*   # NOT pinned
    """

    return any(
        (spec.operator == "==" or spec.operator == "===")
        and not spec.version.endswith(".*")
        for spec in req.specifier
    )


def has_prerelease(req):
    """Returns whether an InstallRequirement has a prerelease specifier"""
    return any(parse_version(spec.version).is_prerelease for spec in req.specifier)


def have_compatible_glibc(major, minimum_minor):
    """Pulled from PEP 513"""
    import ctypes  # pylint: disable=bad-option-value,import-outside-toplevel

    process_namespace = ctypes.CDLL(None)
    try:
        gnu_get_libc_version = process_namespace.gnu_get_libc_version
    except AttributeError:
        # Symbol doesn't exist -> therefore, we are not linked to
        # glibc.
        return False

    # Call gnu_get_libc_version, which returns a string like "2.5".
    gnu_get_libc_version.restype = ctypes.c_char_p
    version_str = gnu_get_libc_version()
    # py2 / py3 compatibility:
    if not isinstance(version_str, str):
        version_str = version_str.decode("ascii")

    # Parse string and check against requested version.
    version = [int(piece) for piece in version_str.split(".")]
    assert len(version) == 2
    if major != version[0]:
        return False
    if minimum_minor > version[1]:
        return False
    return True
