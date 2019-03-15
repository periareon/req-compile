import logging
import os

import pkg_resources

from qer import utils
import qer.repos.repository
from qer.repos.repository import Repository


class FindLinksRepository(Repository):
    def __init__(self, path, allow_prerelease=None):
        super(FindLinksRepository, self).__init__(allow_prerelease=allow_prerelease)
        self.path = path
        self._logger = logging.getLogger('qer.repository.findlinks')
        self.links = []
        self._find_all_links()

    def __repr__(self):
        return '--find-links {}'.format(self.path)

    def _find_all_links(self):
        for filename in os.listdir(self.path):
            candidate = qer.repos.repository.process_distribution(None, filename)
            if candidate is not None:
                self.links.append(candidate)

    @property
    def logger(self):
        return self._logger

    def get_candidates(self, req):
        project_name = utils.normalize_project_name(req.name)
        results = []
        for candidate in self.links:
            if utils.normalize_project_name(candidate.name) == project_name:
                results.append(candidate)

        return results

    def resolve_candidate(self, candidate):
        return os.path.join(self.path, candidate.filename), True

    def close(self):
        pass


if __name__ == '__main__':
    repo = FindLinksRepository('mywheels')
    print(repo.get_candidate(pkg_resources.Requirement.parse('astroid')))
