from __future__ import print_function
import argparse
import logging
import string

import pkg_resources
import requests

import qer.compile
import qer.metadata
import qer.pypi


ROOT_REQ = 'root'


def _generate_lines(dists):
    blacklist = [
        qer.compile.DistributionCollection.CONSTRAINTS_ENTRY,
        ROOT_REQ,
        'setuptools'
    ]
    for dist in dists.dists.itervalues():
        if dist.metadata.name in blacklist:
            continue

        constraints = dists.build_constraints(dist.metadata.name)
        if constraints is not None and constraints.specifier:
            constraints = str(constraints.specifier)
        else:
            constraints = ''

        if not dist.sources or dist.sources == {ROOT_REQ}:
            transitive = ' '
        else:
            transitive = ' via ' + ', '.join(dist.sources) + ' '

        constraint = '{}=={}'.format(dist.metadata.name, dist.metadata.version).ljust(40)
        yield '{}# {}{}'.format(constraint, transitive, constraints)


def run_compile(input_requirements, index_url):
    input_reqs = open(input_requirements, 'r').readlines()
    roots = pkg_resources.parse_requirements(input_reqs)

    results = qer.compile.DistributionCollection()

    root_req = pkg_resources.Requirement.parse(ROOT_REQ)

    metadata = qer.metadata.DistInfo()
    metadata.name = ROOT_REQ
    metadata.version = '0'
    metadata.reqs = list(roots)
    results.add_dist(metadata, ROOT_REQ)

    with qer.pypi.start_session() as session:
        qer.compile.compile_roots(root_req, ROOT_REQ, dists=results,
                                  toplevel=root_req, index_url=index_url, session=session)

        lines = sorted(_generate_lines(results), key=string.lower)
        print('\n'.join(lines))


def main():
    logging.basicConfig()
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger('qer.net').setLevel(logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument('input_requirements', type=str)
    parser.add_argument('--index-url', type=str, default=None)

    args = parser.parse_args()
    run_compile(args.input_requirements, args.index_url)


if __name__ == '__main__':
    main()
