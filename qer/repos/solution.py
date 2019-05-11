from __future__ import print_function

import logging
import sys
from collections import defaultdict

import six
from six.moves import map as imap

import qer.dists
import qer.utils

from qer import utils

from .repository import Repository, Candidate, DistributionType, RequiresPython


class SolutionRepository(Repository):
    def __init__(self, filename, allow_prerelease=None):
        super(SolutionRepository, self).__init__(allow_prerelease=allow_prerelease)
        self.filename = filename
        self.solution = load_from_file(self.filename)
        self._logger = logging.getLogger('qer.repository.solution')

    def __repr__(self):
        return '--solution {}'.format(self.filename)

    @property
    def logger(self):
        return self._logger

    def get_candidates(self, req):
        try:
            node = self.solution[req.name]
            candidate = Candidate(
                node.key,
                node.metadata,
                node.metadata.version,
                RequiresPython(None),
                'any',
                None,
                DistributionType.SOURCE)
            candidate.preparsed = node.metadata
            return [candidate]
        except KeyError:
            return []

    def resolve_candidate(self, candidate):
        return candidate.filename, True

    def close(self):
        pass


def load_from_file(filename):
    result = qer.dists.DistributionCollection()

    with open(filename) as reqfile:
        for line in reqfile.readlines():
            req_part, _, source_part = line.partition('#')
            req = qer.utils.parse_requirement(req_part)
            source_part = source_part.strip()

            sources = source_part.split(', ')

            pkg_names = imap(lambda x: x.split(' ')[0], sources)
            constraints = imap(lambda x: x.split(' ')[1].replace('(', '').replace(')', '') if '(' in x else None, sources)

            version = qer.utils.parse_version(list(req.specifier)[0].version)
            metadata = qer.dists.DistInfo(req.name, version, [])
            result.add_dist(metadata, None, req)

            for name, constraints in zip(pkg_names, constraints):
                if name and not (name.endswith('.txt') or name.endswith('.out')):
                    constraint_req = qer.utils.parse_requirement(name)
                    result.add_dist(constraint_req.name, None, constraint_req)
                    reverse_dep = result[name]
                else:
                    reverse_dep = None
                result.add_dist(metadata.name,
                                reverse_dep,
                                qer.utils.parse_requirement('{}{}{}'.format(metadata.name,
                                                                            ('[' + ','.join(req.extras) + ']') if req.extras else '',
                                                                            constraints if constraints else '')))

    nodes_to_remove = []
    for node in result:
        if node.metadata is not None:
            try:
                requirements = [value for dep_node, value in six.iteritems(node.dependencies)
                                if dep_node.metadata.name != node.metadata.name]
                if node.extra:
                    requirements = [qer.utils.parse_requirement('{} ; extra=="{}"'.format(req, node.extra))
                                    for req in requirements]
                node.metadata.reqs.extend(requirements)
            except Exception:
                print('Error while processing requirement {}'.format(node), file=sys.stderr)
                raise
        else:
            nodes_to_remove.append(node)

    # for root_req in req_mapping:
    #     for req in req_mapping[root_req]:
    #         req_constraints = req_mapping[root_req][req][0] or ''
    #         if '[' in root_req:
    #             req_name, extras = root_req.split('[')
    #             extras = extras.replace(']', '')
    #             extras = extras.split(',')
    #             for extra in extras:
    #                 result.nodes[qer.utils.normalize_project_name(req_name)].metadata.reqs.append(
    #                     qer.utils.parse_requirement(req + req_constraints + ' ; extra=="{}"'.format(extra)))
    #         else:
    #             result.nodes[qer.utils.normalize_project_name(root_req)].metadata.reqs.append(qer.utils.parse_requirement(req + req_constraints))
    for node in nodes_to_remove:
        try:
            del result.nodes[node.key]
        except KeyError:
            pass
    return result
