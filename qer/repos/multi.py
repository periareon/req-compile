from qer.repos.repository import Repository, BaseRepository, NoCandidateException


class MultiRepository(BaseRepository):
    def __init__(self, *repositories):
        super(MultiRepository, self).__init__()
        self.repositories = list(repositories)  # type: list[Repository]
        self.source = {}

    def __repr__(self):
        return ', '.join(repr(repo) for repo in self.repositories)

    def __iter__(self):
        return iter(self.repositories)

    def __hash__(self):
        return hash(self.repositories)

    def get_candidate(self, req):
        last_ex = None
        for repo in self.repositories:
            try:
                candidates = repo.get_candidates(req)
                result = repo._do_get_candidate(req, candidates)
                self.source[req.name] = repo
                return result
            except NoCandidateException as ex:
                last_ex = ex
        raise last_ex

    def get_candidates(self, req):
        candidates = []
        for repo in self.repositories:
            try:
                repo_candidates = repo.get_candidates(req)
                candidates.extend(repo_candidates)
            except NoCandidateException as ex:
                pass
        return candidates
