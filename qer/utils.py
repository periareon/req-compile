import itertools
import os
from collections import defaultdict
import logging

import functools32
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


@functools32.lru_cache(maxsize=1500)
def parse_requirement(req_text):
    return pkg_resources.Requirement.parse(req_text)


def parse_requirements(reqs):
    for req in reqs:
        yield parse_requirement(req)


@functools32.lru_cache(maxsize=1000)
def merge_requirements(req1, req2):
    if req1 is not None and req2 is None:
        return req1
    if req2 is not None and req1 is None:
        return req2

    assert normalize_project_name(req1.name) == normalize_project_name(req2.name)
    all_specs = set(req1.specs or []) | set(req2.specs or [])
    if req1.marker and req2.marker and str(req1.marker) != str(req2.marker):
        if str(req1.marker) in str(req2.marker):
            new_marker = ';' + str(req2.marker)
        elif str(req2.marker) in str(req1.marker):
            new_marker = ';' + str(req1.marker)
        else:
            new_marker = ';' + str(req1.marker) + ' and ' + str(req2.marker)
    elif req1.marker:
        new_marker = ';' + str(req1.marker)
    elif req2.marker:
        new_marker = ';' + str(req2.marker)
    else:
        new_marker = ''

    req_str = normalize_project_name(req1.name) + ','.join(''.join(parts) for parts in all_specs) + new_marker
    return parse_requirement(req_str)


@functools32.lru_cache(maxsize=500)
def normalize_project_name(project_name):
    return project_name.lower().replace('-', '_').replace('.', '_')
