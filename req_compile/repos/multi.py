import itertools

from req_compile.errors import NoCandidateException
from req_compile.repos.repository import BaseRepository


class MultiRepository(BaseRepository):
    def __init__(self, *repositories):
        super(MultiRepository, self).__init__()
        self.repositories = list(repositories)

    def __repr__(self):
        return ", ".join(repr(repo) for repo in self)

    def __iter__(self):
        # Expand nested MultiRepositories as well
        return itertools.chain(*(iter(repo) for repo in self.repositories))

    def __hash__(self):
        return hash(self.repositories)

    def get_candidate(self, req, max_downgrade=None):
        last_ex = NoCandidateException(req)
        for repo in self.repositories:
            try:
                return repo.get_candidate(req, max_downgrade=max_downgrade)
            except NoCandidateException as ex:
                last_ex = ex
        raise last_ex

    def get_candidates(self, req):
        candidates = []
        for repo in self.repositories:
            try:
                repo_candidates = repo.get_candidates(req)
                candidates.extend(repo_candidates)
            except NoCandidateException:
                pass
        return candidates
