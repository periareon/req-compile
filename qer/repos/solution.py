from __future__ import print_function

import logging

from qer import utils
from qer.solution import load_from_file

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
