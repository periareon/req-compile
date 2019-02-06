from __future__ import print_function

import argparse
import logging
import string
from contextlib import closing

import pkg_resources

import qer.compile
import qer.metadata
import qer.pypi
from qer import utils

ROOT_REQ = 'root'

BLACKLIST = [
    qer.compile.DistributionCollection.CONSTRAINTS_ENTRY,
    ROOT_REQ,
    'setuptools'
]


def _get_reason_constraint(dists, constraint_dists, project_name):
    components = dists.get_reverse_deps(project_name)
    if not components:
        constraints = ''
    else:
        constraints = []
        for component in components:
            if component == ROOT_REQ:
                continue
            for req in dists.dists[component].metadata.reqs:
                if req.name == project_name:
                    if component == qer.compile.DistributionCollection.CONSTRAINTS_ENTRY:
                        constraints_reason = _get_reason_constraint(constraint_dists, None, project_name)
                        if constraints_reason:
                            constraints += ['(via constraints: ' + constraints_reason + ')']
                    else:
                        specifics = ' (' + str(req.specifier) + ')' if req.specifier else ''
                        constraints += [component + specifics]
                        break
        constraints = ', '.join(constraints)
    return constraints


def _generate_lines(dists, constraint_dists):
    for dist in dists.dists.itervalues():
        if dist.metadata.name in BLACKLIST:
            continue

        constraints = _get_reason_constraint(dists, constraint_dists, dist.metadata.name)

        constraint = '{}=={}'.format(dist.metadata.name, dist.metadata.version).ljust(40)
        yield '{}# {}'.format(constraint, constraints)


def _generate_constraints(dists):
    for dist in dists.dists.itervalues():
        if dist.metadata.name in BLACKLIST:
            continue

        req = dists.build_constraints(dist.metadata.name)
        if req.specifier:
            yield req


def _build_root_metadata(roots):
    metadata = qer.metadata.DistInfo()
    metadata.name = ROOT_REQ
    metadata.version = '0'
    metadata.reqs = list(roots)
    return metadata


def run_compile(input_reqfiles, constraint_files, index_url):
    root_req = pkg_resources.Requirement.parse(ROOT_REQ)

    constraint_roots = []
    if constraint_files:
        for constraint_file in constraint_files:
            with open(constraint_file, 'r') as handle:
                constraint_roots += pkg_resources.parse_requirements(handle.readlines())

    constraint_results = qer.compile.DistributionCollection()
    constraint_results.add_dist(_build_root_metadata(constraint_roots), ROOT_REQ)

    with closing(qer.pypi.start_session()) as session:
        qer.compile.compile_roots(root_req, ROOT_REQ, dists=constraint_results,
                                  toplevel=root_req, index_url=index_url, session=session)

    constraints = list(_generate_constraints(constraint_results))

    roots = utils.reqs_from_files(input_reqfiles)
    results = qer.compile.DistributionCollection(constraints)
    results.add_dist(_build_root_metadata(roots), ROOT_REQ)

    with closing(qer.pypi.start_session()) as session:
        qer.compile.compile_roots(root_req, ROOT_REQ, dists=results,
                                  toplevel=root_req, index_url=index_url, session=session)

        lines = sorted(_generate_lines(results, constraint_results), key=string.lower)
        print('\n'.join(lines))


def compile_main():
    logging.basicConfig(level=logging.DEBUG)
    # logging.getLogger('qer.net').setLevel(logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument('requirement_files', nargs='+', help='Input requirements files')
    parser.add_argument('-i', '--index-url', type=str, default=None)
    parser.add_argument('-c', '--constraints', nargs='+', help='Contraints files. Not included in final compilation')

    args = parser.parse_args()
    run_compile(args.requirement_files, args.constraints if args.constraints else None, args.index_url)


if __name__ == '__main__':
    compile_main()
