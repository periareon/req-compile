from __future__ import print_function
import collections
import logging
import os

from qer import utils
import qer.metadata
import qer.repos.repository

from qer.repos.repository import Repository


SPECIAL_DIRS = ('site-packages', 'dist-packages', '.git', '.svn', '.idea')
SPECIAL_FILES  = ('__init__.py',)


class SourceRepository(Repository):
    def __init__(self, path, allow_prerelease=None):
        super(SourceRepository, self).__init__(allow_prerelease=allow_prerelease)
        self.path = path
        self._logger = logging.getLogger('qer.repository.source')
        self.distributions = collections.defaultdict(list)
        self._find_all_distributions()

    def _find_all_distributions(self):
        for root, dirs, files in os.walk(self.path):
            for dir_ in dirs:
                if dir_ in SPECIAL_DIRS:
                    dirs.remove(dir_)

            for file in files:
                if file in SPECIAL_FILES:
                    for dir_ in dirs:
                        dirs.remove(dir_)
                elif file == 'setup.py':
                    for dir_ in list(dirs):
                        dirs.remove(dir_)

                    result = qer.metadata.extract_metadata(root)
                    candidate = qer.repos.repository.Candidate(
                        result.name,
                        root,
                        result.version,
                        qer.repos.repository.RequiresPython(None),
                        'any',
                        None,
                        qer.repos.repository.DistributionType.SOURCE)
                    candidate.preparsed = result
                    self.distributions[utils.normalize_project_name(result.name)].append(candidate)
                    break

    def __repr__(self):
        return '--source {}'.format(self.path)

    @property
    def logger(self):
        return self._logger

    def get_candidates(self, req):
        project_name = utils.normalize_project_name(req.name)
        return self.distributions.get(project_name, [])

    def resolve_candidate(self, candidate):
        return candidate.filename, True

    def close(self):
        pass
