import os

from qer import utils
import qer.repos.repository
from qer.repos.repository import Repository
import qer.metadata


class FindLinksRepository(Repository):
    def __init__(self, path, allow_prerelease=None):
        super(FindLinksRepository, self).__init__('findlinks', allow_prerelease=allow_prerelease)
        self.path = path
        self.links = []
        self._find_all_links()

    def __repr__(self):
        return '--find-links {}'.format(self.path)

    def __eq__(self, other):
        return (isinstance(other, FindLinksRepository) and
                super(FindLinksRepository, self).__eq__(other) and
                self.path == other.path)

    def __hash__(self):
        return hash('findlinks') ^ hash(self.path)

    def _find_all_links(self):
        for filename in os.listdir(self.path):
            candidate = qer.repos.repository.process_distribution(None, filename)
            if candidate is not None:
                self.links.append(candidate)

    def get_candidates(self, req):
        project_name = None
        if req is not None:
            project_name = utils.normalize_project_name(req.name)
        results = []
        for candidate in self.links:
            if req is None or utils.normalize_project_name(candidate.name) == project_name:
                results.append(candidate)

        return results

    def resolve_candidate(self, candidate):
        filename = os.path.join(self.path, candidate.filename)
        return qer.metadata.extract_metadata(filename, origin=self), True

    def close(self):
        pass
