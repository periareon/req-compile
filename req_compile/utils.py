import logging
import os
import typing
from collections import defaultdict
from functools import lru_cache
from typing import DefaultDict, Dict, Iterable, Optional, Tuple

import packaging.version
import pkg_resources


def reduce_requirements(
    raw_reqs: Iterable[pkg_resources.Requirement],
) -> Iterable[pkg_resources.Requirement]:
    """Reduce a list of requirements to a minimal list.

    Combine requirements with the same key.
    """
    reqs: DefaultDict[str, Optional[pkg_resources.Requirement]] = defaultdict(
        lambda: None
    )
    for req in raw_reqs:
        reqs[req.project_name] = merge_requirements(reqs[req.project_name], req)

    return list(req for req in reqs.values() if req is not None)


class CommentError(ValueError):
    def __str__(self):
        return "Text given is a comment"


@lru_cache(maxsize=None)
def parse_requirement(req_text: str) -> pkg_resources.Requirement:
    """Parse a string into a Requirement object.

    Args:
        req_text (str): The pkg_resources style requirement string,
            e.g. flask==1.1 ; python_version >= '3.0'

    Returns:
        (pkg_resources.Requirement) The parsed requirement.

    Raises:
        A flavor of a ValueError if the requirement string is invalid.
    """
    req_text = req_text.strip()
    if not req_text:
        raise ValueError("No requirement given")
    if req_text[0] == "#":
        raise CommentError
    return pkg_resources.Requirement.parse(req_text)


@lru_cache(maxsize=None)
def parse_version(version: str) -> packaging.version.Version:
    """Parse a string into a packaging version.

    Args:
        version: Version to parse
    """
    return pkg_resources.parse_version(version)


def parse_requirements(reqs: Iterable[str]) -> Iterable[pkg_resources.Requirement]:
    """Parse a list of strings into Requirements."""
    for req in reqs:
        req = req.strip().rstrip("\\")
        if "\n" in req:
            for inner_req in parse_requirements(req.split("\n")):
                yield inner_req
        else:
            if not req:
                continue
            if req[0] == "#" or req.startswith("--"):
                continue
            result = parse_requirement(req)
            if result is not None:
                yield result


def req_iter_from_file(
    reqfile_name: str, parameters: typing.List[str]
) -> Iterable[pkg_resources.Requirement]:
    """Create an iterator to step through a requirements file."""
    with open(reqfile_name, "r", encoding="utf-8") as reqfile:
        lines = reqfile.readlines()

    return req_iter_from_lines(
        lines, parameters, relative_dir=os.path.dirname(reqfile_name)
    )


def req_iter_from_lines(
    lines: Iterable[str], parameters: typing.List[str], relative_dir: str = None
) -> Iterable[pkg_resources.Requirement]:
    full_line = ""
    continuation = False

    for req_line in lines:
        req_line = req_line.strip()
        if not req_line:
            continue

        if req_line.startswith("#"):
            continue

        if continuation or not full_line:
            full_line += req_line.rstrip("\\")

        if "\\" in req_line:
            if req_line[-1] != "\\":
                raise ValueError(
                    "Line continuation marker \\ must be last character in a line"
                )
            continuation = True
            continue

        continuation = False

        line_parts = full_line.split()
        if line_parts[0] in ("-r", "--requirement"):
            for req in req_iter_from_file(
                os.path.join(relative_dir or ".", line_parts[1].strip()),
                parameters,
            ):
                yield req
        elif line_parts[0].startswith("-"):
            parameters.extend(line_parts)
        else:
            try:
                if len(line_parts) > 1:
                    for idx, part in enumerate(line_parts):
                        if part.startswith("--hash"):
                            full_line = " ".join(line_parts[:idx])
                            break
                yield parse_requirement(full_line)
            except ValueError:
                logging.getLogger("req_compile.utils").exception(
                    "Failed to parse %s", full_line
                )
                raise

        full_line = ""


def merge_extras(
    extras1: Optional[Iterable[str]], extras2: Optional[Iterable[str]]
) -> Iterable[str]:
    """Merge two iterables of extra into a single sorted tuple. Case-sensitive."""
    if extras1 and extras2:
        return tuple(sorted(set(extras1) | set(extras2)))

    if not extras1 and extras2:
        return extras2
    if not extras2 and extras1:
        return extras1
    return []


def merge_requirements(
    req1: Optional[pkg_resources.Requirement],
    req2: Optional[pkg_resources.Requirement],
) -> pkg_resources.Requirement:
    """Merge two requirements into a single requirement that would satisfy both."""
    if req1 is not None and req2 is None:
        return req1
    if req2 is not None and req1 is None:
        return req2

    assert req1 is not None
    assert req2 is not None

    req1_name_norm = normalize_project_name(req1.name)
    if req1_name_norm != normalize_project_name(req2.name):
        raise ValueError("Reqs don't match: {} != {}".format(req1, req2))
    all_specs = set(req1.specifier) | set(req2.specifier)

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
        + ",".join(str(part) for part in all_specs)
        + new_marker
    )
    return parse_requirement(req_str)


NormName = typing.NewType("NormName", str)

NAME_CACHE = {}  # type: Dict[str, NormName]


def normalize_project_name(project_name: str) -> NormName:
    """Normalize a project name."""
    if project_name in NAME_CACHE:
        return NAME_CACHE[project_name]
    value = NormName(
        project_name.lower().replace("-", "_").replace(".", "_").replace(" ", "_")
    )
    NAME_CACHE[project_name] = value
    return value


def is_pinned_requirement(req: pkg_resources.Requirement) -> bool:
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


def has_prerelease(req: pkg_resources.Requirement) -> bool:
    """Returns whether an InstallRequirement has a prerelease specifier."""
    return any(parse_version(spec.version).is_prerelease for spec in req.specifier)


@lru_cache(maxsize=None)
def get_glibc_version():
    # type: () -> Optional[Tuple[int, int]]
    """Based on PEP 513/600."""
    import ctypes  # pylint: disable=bad-option-value,import-outside-toplevel

    try:
        process_namespace = ctypes.CDLL(None)
        gnu_get_libc_version = process_namespace.gnu_get_libc_version
    except (AttributeError, TypeError):
        # Symbol doesn't exist -> therefore, we are not linked to
        # glibc.
        return None

    # Call gnu_get_libc_version, which returns a string like "2.5".
    gnu_get_libc_version.restype = ctypes.c_char_p
    version_str = gnu_get_libc_version()
    # py2 / py3 compatibility:
    if not isinstance(version_str, str):
        version_str = version_str.decode("ascii")

    # Parse string and check against requested version.
    version = [int(piece) for piece in version_str.split(".")]
    assert len(version) == 2
    return version[0], version[1]
