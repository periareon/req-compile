import argparse
import logging
from collections import defaultdict

from hashlib import sha256

from qer.utils import merge_requirements
import qer.utils


def run_hash(reqs):
    """
    Args:
        reqs (list[pkg_resources.Requirement]): Requirements files
    """
    reqs = defaultdict(lambda: None)
    for req in reqs:
        reqs[req.name] = merge_requirements(reqs[req.name], req)

    hasher = sha256()
    for req in reqs.values():
        hasher.update(str(req).encode('utf-8'))
    return hasher.hexdigest()


def hash_main():
    logging.basicConfig(level=logging.DEBUG)

    parser = argparse.ArgumentParser()
    parser.add_argument('requirement_files', nargs='+', help='Input requirements files')

    args = parser.parse_args()

    print(run_hash(qer.utils.reqs_from_files(args.requirement_files)))


if __name__ == '__main__':
    hash_main()
