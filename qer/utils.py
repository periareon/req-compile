import itertools

import pkg_resources


def _req_iter_from_file(reqfile_name):
    with open(reqfile_name, 'r') as reqfile:
        return pkg_resources.parse_requirements(reqfile.readlines())


def reqs_from_files(requirements_files):
    """
    Args:
        requirements_files (list[str]): Requirements files
    """
    raw_reqs = iter([])
    for reqfile_name in requirements_files:
        raw_reqs = itertools.chain(raw_reqs, _req_iter_from_file(reqfile_name))
    return raw_reqs
