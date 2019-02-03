from __future__ import print_function
import argparse
import logging

import pkg_resources

import qer.compile
import qer.metadata


def _generate_lines(dists):
    for dist in dists.dists.itervalues():
        if dist.metadata.name == qer.compile.DistributionCollection.CONSTRAINTS_ENTRY:
            continue

        constraints = dists.build_constraints(dist.metadata.name)
        if constraints is not None:
            constraints = '- ' + str(constraints.specifier)
        else:
            constraints = ''
        yield '{}=={} # via {} {}'.format(dist.metadata.name, dist.metadata.version, ','.join(dist.sources),
                                          constraints)


def run_compile(input_requirements):

    input_reqs = open(input_requirements, 'r').readlines()
    roots = pkg_resources.parse_requirements(input_reqs)

    results = qer.compile.DistributionCollection()
    ROOT_REQ = 'root'
    root_req = pkg_resources.Requirement.parse(ROOT_REQ)

    metadata = qer.metadata.DistInfo()
    metadata.name = ROOT_REQ
    metadata.version = '0'
    metadata.reqs = list(roots)
    results.add_dist(metadata, ROOT_REQ)

    qer.compile.compile_roots(root_req, ROOT_REQ, dists=results, toplevel=root_req)

    lines = sorted(_generate_lines(results))
    print('\n'.join(lines))


def main():
    logging.basicConfig()
    logging.getLogger('qer.net').setLevel(logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument('input_requirements', type=str)
    # parser.add_argument('output_file', type=str)

    args = parser.parse_args()
    run_compile(args.input_requirements)


if __name__ == '__main__':
    main()
