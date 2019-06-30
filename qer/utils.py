import itertools
import os
from collections import defaultdict
import logging

try:
    from functools32 import lru_cache
except ImportError:
    from functools import lru_cache

import pkg_resources


def _req_iter_from_file(reqfile_name):
    with open(reqfile_name, 'r') as reqfile:
        for req_line in reqfile:
            req_line = req_line.strip()
            if not req_line:
                continue
            if req_line.startswith('-r'):
                for req in _req_iter_from_file(os.path.join(
                        os.path.dirname(reqfile_name),
                        req_line.split(' ')[1].strip())):
                    yield req
            elif req_line.startswith('--index-url') or req_line.startswith('--extra-index-url'):
                pass
            elif req_line.startswith('#'):
                pass
            else:
                try:
                    yield parse_requirement(req_line)
                except ValueError:
                    logging.getLogger('req.utils').exception('Failed to parse %s', req_line)
                    raise


def reqs_from_files(requirements_files):
    """
    Args:
        requirements_files (list[str]): Requirements files
    """
    raw_reqs = iter([])
    for reqfile_name in requirements_files:
        raw_reqs = itertools.chain(raw_reqs, _req_iter_from_file(reqfile_name))

    reqs = defaultdict(lambda: None)
    for req in raw_reqs:
        reqs[req.name] = merge_requirements(reqs[req.name], req)

    return list(reqs.values())


@lru_cache(maxsize=None)
def parse_requirement(req_text):
    if req_text[0] == '#':
        return None
    if not req_text.strip():
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
    for req in reqs:
        result = parse_requirement(req)
        if result is not None:
            yield result


def merge_extras(extras1, extras2):
    if not extras1:
        return extras2
    if not extras2:
        return extras1
    return tuple(sorted(list(set(extras1) | set(extras2))))


def merge_requirements(req1, req2):
    if req1 is not None and req2 is None:
        return req1
    if req2 is not None and req1 is None:
        return req2

    req1_name_norm = normalize_project_name(req1.name)
    assert req1_name_norm == normalize_project_name(req2.name)
    all_specs = set(req1.specs or []) | set(req2.specs or [])

    # Handle markers
    if req1.marker and req2.marker:
        if str(req1.marker) != str(req2.marker):
            if str(req1.marker) in str(req2.marker):
                new_marker = ';' + str(req1.marker)
            elif str(req2.marker) in str(req1.marker):
                new_marker = ';' + str(req2.marker)
            else:
                new_marker = ''
        else:
            new_marker = ';' + str(req1.marker)
    else:
        new_marker = ''

    extras = merge_extras(req1.extras, req2.extras)
    extras_str = ''
    if extras:
        extras_str = '[' + ','.join(extras) + ']'
    req_str = req1_name_norm + extras_str + ','.join(''.join(parts) for parts in all_specs) + new_marker
    return parse_requirement(req_str)


NAME_CACHE = {}


def normalize_project_name(project_name):
    if project_name in NAME_CACHE:
        return NAME_CACHE[project_name]
    value = project_name.lower().replace('-', '_') #.replace('.', '_')
    NAME_CACHE[project_name] = value
    return value


def filter_req(req, extra):
    if extra and not req.marker:
        return False
    keep_req = True
    if req.marker:
        keep_req = req.marker.evaluate({'extra': extra})
    return keep_req


def is_pinned_requirement(req):
    """
    Returns whether an InstallRequirement is a "pinned" requirement.

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

    return any((spec.operator == '==' or spec.operator == '===') and not spec.version.endswith('.*')
               for spec in req.specifier)
