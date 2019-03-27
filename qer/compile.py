"""Logic for compiling requirements"""
from __future__ import print_function

import logging

import pkg_resources
import six

import qer.dists
import qer.metadata
import qer.repos.pypi
import qer.utils
import qer.repos.repository

from qer.dists import DistributionCollection
from qer.utils import normalize_project_name


ROOT_REQ = 'root__a'
CONSTRAINTS_REQ = 'constraints__a'

BLACKLIST = [
    'setuptools'
]


def compile_roots(node, source, repo, dists, depth=1, verbose=True):
    """

    Args:
        node (qer.dists.DependencyNode):
        source (DependencyNode):
        repo (Repository):
        dists (DistributionCollection):
        depth:
        verbose:

    Returns:

    """
    logger = logging.getLogger('qer.compile')

    if verbose:
        print(' ' * depth + node.key, end='')

    nodes_to_recurse = set()
    if node.metadata is not None and not node.metadata.invalid:
        if verbose:
            print(' ... REUSE')
        logger.info('Reusing dist %s %s', node.metadata.name, node.metadata.version)

        # if node.metadata.meta:
        nodes_to_recurse = {node}
        recurse_reqs = True
    else:
        while True:
            spec_req = node.build_constraints()
            dist, cached = repo.get_candidate(spec_req)
            source_repo = repo.source_of(spec_req)

            if verbose:
                if cached:
                    print(' ... CACHED ({})'.format(source_repo))
                else:
                    print(' ... DOWNLOAD ({})'.format(source_repo))

            metadata = qer.metadata.extract_metadata(dist, origin=source_repo)
            try:
                nodes_to_recurse = dists.add_dist(metadata, source, source.dependencies[node])
                break
            except qer.dists.ConstraintViolatedException as ex:
                print('---------- VIOLATED ({}) -------------'.format(ex.node))
                pass

        recurse_reqs = True

    if nodes_to_recurse:
        for recurse_node in nodes_to_recurse:
            for req in list(recurse_node.dependencies):
                compile_roots(req, recurse_node, repo, dists, depth=depth + 1, verbose=verbose)


def _generate_constraints(dists):
    for dist in dists:
        if dist.metadata.name in BLACKLIST:
            continue
        if dist.metadata.name.startswith(ROOT_REQ):
            continue

        req = dists.build_constraints(dist.metadata.name)
        if req.specifier:
            yield req


def _build_root_metadata(roots, name):
    return qer.dists.DistInfo(name, '0', roots, meta=True)


def perform_compile(input_reqs, wheeldir, repo, constraint_reqs=None, solution=None):
    """
    Perform a compilation using the given inputs and constraints
    Args:
        input_reqs (list[pkg_resources.Requirement] or
                    dict[str, list[pkg_resources.Requirement]]):
            List of mapping of input requirements. If provided a mapping,
            requirements will be kept separate during compilation for better
            insight into the resolved requirements
        wheeldir (str): Location to download wheels to and to use as a cache
        constraint_reqs (list[pkg_resources.Requirement] or None): Constraints to use
            when compiling
        solution (DistributionCollection): Optionally, provide a possible solution
            to consider when compiling. Existing distributions will be modified as
            necessary to solve the solution
    Returns:
        tuple[DistributionCollection, DistributionCollection, dict]
    """
    results = qer.dists.DistributionCollection()

    if constraint_reqs:
        constraint_node = results.add_dist(qer.dists.RequirementsFile(CONSTRAINTS_REQ, constraint_reqs), None, None)

    root_mapping = {}
    nodes = set()
    if isinstance(input_reqs, dict):
        fake_reqs = []
        for idx, req_source in enumerate(input_reqs):
            roots = input_reqs[req_source]
            name = '{}{}'.format(ROOT_REQ, idx)
            root_mapping[name] = req_source
            fake_reqs.append(pkg_resources.Requirement(name))
            nodes |= results.add_dist(qer.dists.RequirementsFile(req_source, roots), None, None)
    else:
        nodes |= results.add_dist(qer.dists.RequirementsFile(ROOT_REQ, input_reqs), None, None)

    for node in nodes:
        compile_roots(node, None, repo, dists=results)

    if constraint_reqs:
        results.remove_dists(list(constraint_node)[0])

    for node in results:
        if node.metadata is None or node.metadata.invalid:
            raise qer.repos.repository.NoCandidateException()
    return results, None, root_mapping
