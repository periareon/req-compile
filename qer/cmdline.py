from __future__ import print_function

import argparse
import logging
import os
import string
import sys
from contextlib import closing

import pkg_resources

import qer.compile
import qer.metadata
import qer.pypi
from qer import utils

ROOT_REQ = 'root__a'

BLACKLIST = [
    qer.compile.DistributionCollection.CONSTRAINTS_ENTRY,
    'setuptools'
]


def _get_reason_constraint(dists, constraint_dists, project_name, root_mapping):
    project_name = utils.normalize_project_name(project_name)
    components = dists.get_reverse_deps(project_name)
    if not components:
        constraints = ''
    else:
        constraints = []
        for component in components:
            if component == ROOT_REQ:
                continue
            for req in dists.dists[component].metadata.reqs:
                if utils.normalize_project_name(req.name) == project_name:
                    if component == qer.compile.DistributionCollection.CONSTRAINTS_ENTRY:
                        constraints_reason = _get_reason_constraint(constraint_dists, None,
                                                                    project_name, root_mapping)
                        if constraints_reason:
                            constraints += ['(via constraints: ' + constraints_reason + ')']
                    else:
                        specifics = ' (' + str(req.specifier) + ')' if req.specifier else ''
                        if component.startswith(ROOT_REQ):
                            component = root_mapping[component]
                        constraints += [component + specifics]
                        break
        constraints = ', '.join(constraints)
    return constraints


def _generate_lines(dists, constraint_dists, root_mapping):
    for dist in dists.dists.itervalues():
        if dist.metadata.name in BLACKLIST:
            continue
        if dist.metadata.name.startswith(ROOT_REQ):
            continue

        constraints = _get_reason_constraint(dists, constraint_dists, dist.metadata.name, root_mapping)

        constraint = '{}=={}'.format(dist.metadata.name, dist.metadata.version).ljust(43)
        yield '{}# {}'.format(constraint, constraints)


def _generate_constraints(dists):
    for dist in dists.dists.itervalues():
        if dist.metadata.name in BLACKLIST:
            continue
        if dist.metadata.name.startswith(ROOT_REQ):
            continue

        req = dists.build_constraints(dist.metadata.name)
        if req.specifier:
            yield req


def _generate_no_candidate_display(ex, dists, constraint_dists, root_mapping):
    project_name = utils.normalize_project_name(ex.project_name)
    components = dists.get_reverse_deps(project_name)
    if not components:
        print('No package available for %s, latest is %s', file=sys.stderr)
    else:
        print('No version of {} could satisfy the following requirements:'.format(ex.project_name), file=sys.stderr)
        for component in components:
            for req in dists.dists[component].metadata.reqs:
                if utils.normalize_project_name(req.name) == project_name:
                    if component == qer.compile.DistributionCollection.CONSTRAINTS_ENTRY:
                        constraints_reason = _get_reason_constraint(constraint_dists, None,
                                                                    project_name, root_mapping)
                        if constraints_reason:
                            print('   ' + constraints_reason, file=sys.stderr)
                    else:
                        specifics = str(req.specifier) if req.specifier else ''
                        if component.startswith(ROOT_REQ):
                            source = root_mapping.get(component, 'input file')
                        else:
                            constraints_reason = _get_reason_constraint(dists, constraint_dists,
                                                                        component, root_mapping)
                            if constraints_reason:
                                constraints_reason = ' (via ' + constraints_reason + ')'
                            source = '{} {}{}'.format(component, dists.dists[component].metadata.version, constraints_reason)

                        print('   {} requires {}{}'.format(source,
                                                           ex.project_name, specifics),
                              file=sys.stderr)
                        break
    sys.exit(1)


def _build_root_metadata(roots, name):
    metadata = qer.metadata.DistInfo()
    metadata.name = name
    metadata.version = '0'
    metadata.reqs = list(roots)
    return metadata


def run_compile(input_reqfiles, constraint_files, index_url, wheeldir, no_combine):
    root_req = utils.parse_requirement(ROOT_REQ)

    if not os.path.exists(wheeldir):
        os.mkdir(wheeldir)

    constraints = None
    constraint_results = qer.compile.DistributionCollection()

    if constraint_files:
        constraint_roots = utils.reqs_from_files(constraint_files)

        constraint_results = qer.compile.DistributionCollection()
        constraint_results.add_dist(_build_root_metadata(constraint_roots, ROOT_REQ), ROOT_REQ)

        with closing(qer.pypi.start_session()) as session:
            qer.compile.compile_roots(root_req, ROOT_REQ, dists=constraint_results,
                                      toplevel=root_req, index_url=index_url, session=session,
                                      wheeldir=wheeldir)

        constraints = list(_generate_constraints(constraint_results))

    results = qer.compile.DistributionCollection(constraints)
    root_mapping = {}
    try:
        if no_combine:
            fake_reqs = []
            idx = 1
            for input_reqfile in input_reqfiles:
                roots = utils.reqs_from_files([input_reqfile])
                name = '{}{}'.format(ROOT_REQ, idx)
                root_mapping[name] = input_reqfile
                dist_info = _build_root_metadata(roots, name)
                fake_reqs.append(pkg_resources.Requirement(name))
                results.add_dist(dist_info,
                                 input_reqfile)
                idx += 1
            results.add_dist(_build_root_metadata(fake_reqs, ROOT_REQ), ROOT_REQ)
        else:
            roots = utils.reqs_from_files(input_reqfiles)
            results.add_dist(_build_root_metadata(roots, ROOT_REQ), ROOT_REQ)

        with closing(qer.pypi.start_session()) as session:
            qer.compile.compile_roots(root_req, ROOT_REQ, dists=results,
                                      toplevel=root_req, index_url=index_url, session=session,
                                      wheeldir=wheeldir)

            lines = sorted(_generate_lines(results, constraint_results, root_mapping), key=string.lower)
            print('\n'.join(lines))
    except qer.pypi.NoCandidateException as ex:
        _generate_no_candidate_display(ex, results, constraint_results, root_mapping)


def compile_main():
    logging.basicConfig(level=logging.ERROR)

    parser = argparse.ArgumentParser()
    parser.add_argument('requirement_files', nargs='+', help='Input requirements files')
    parser.add_argument('-i', '--index-url', type=str, default=None)
    parser.add_argument('-c', '--constraints', action='append',
                        help='Contraints files. Not included in final compilation')
    parser.add_argument('-w', '--wheel-dir', type=str, default=None)
    parser.add_argument('-n', '--no-combine', default=False, action='store_true',
                        help='Keep input requirement file sources separate to '
                             'improve errors and output (slower)')

    args = parser.parse_args()
    run_compile(args.requirement_files, args.constraints if args.constraints else None,
                args.index_url, args.wheel_dir, args.no_combine)


if __name__ == '__main__':
    compile_main()
