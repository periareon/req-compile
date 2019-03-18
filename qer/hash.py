import argparse
import logging
import os
from collections import defaultdict

from hashlib import sha256

import six

from qer.repos.source import SourceRepository
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
    parser.add_argument('requirement_files', nargs='+',
                        help='Input requirements files')
    parser.add_argument('-e', '--extra', nargs='+', default=[],
                        help='Extras to include for every discovered distribution')

    args = parser.parse_args()

    extras = tuple(args.extra)

    if len(args.requirement_files) == 1 and os.path.isdir(args.requirement_files[0]):
        reqs = []
        source_repo = SourceRepository(args.requirement_files[0])
        for candidates in six.itervalues(source_repo.distributions):
            for candidate in candidates:
                reqs.extend(candidate.preparsed.requires(extras=extras))
    else:
        reqs = qer.utils.reqs_from_files(args.requirement_files)

    print(run_hash(reqs))


if __name__ == '__main__':
    hash_main()
