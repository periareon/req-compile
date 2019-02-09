import itertools
from collections import defaultdict

import pkg_resources

from qer.compile import _merge_requirements


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

    reqs = defaultdict(lambda: None)
    for req in raw_reqs:
        reqs[req.name] = _merge_requirements(reqs[req.name], req)

    return list(reqs.values())
