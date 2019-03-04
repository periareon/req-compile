import logging
import os

import pkg_resources

from qer import utils
from qer.repository import Repository, Candidate, NoCandidateException


class FindLinksRepository(Repository):
    def __init__(self, path, allow_prerelease=None):
        super(FindLinksRepository, self).__init__(allow_prerelease=allow_prerelease)
        self.path = path
        self._logger = logging.getLogger('qer.repository.findlinks')
        self.links = []
        self._find_all_links()

    def __repr__(self):
        return 'FindLinksRepository({})'.format(self.path)

    def _find_all_links(self):
        for filename in os.listdir(self.path):
            if filename.lower().endswith('.whl'):
                self.links.append(self._build_wheel_candidate(filename))

    def _build_wheel_candidate(self, filename):
        data_parts = filename.split('-')
        name = utils.normalize_project_name(data_parts[0])
        version = pkg_resources.parse_version(data_parts[1])
        platform = data_parts[4].split('.')[0]
        return Candidate(name,
                         filename,
                         version,
                         tuple(data_parts[2].split('.')),
                         platform,
                         None)

    @property
    def logger(self):
        return self._logger

    def get_candidates(self, req):
        project_name = utils.normalize_project_name(req.name)
        results = []
        for candidate in self.links:
            if candidate.name == project_name:
                results.append(candidate)

        if not results:
            raise NoCandidateException()

        return results

    def resolve_candidate(self, candidate):
        return os.path.join(self.path, candidate.filename), True

    def close(self):
        pass


if __name__ == '__main__':
    repo = FindLinksRepository('mywheels')
    print(repo.get_candidate(pkg_resources.Requirement.parse('astroid')))
