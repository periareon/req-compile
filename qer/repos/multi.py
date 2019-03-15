from qer.repos.repository import Repository, BaseRepository, NoCandidateException


class MultiRepository(BaseRepository):
    def __init__(self, *repositories):
        super(MultiRepository, self).__init__()
        self.repositories = list(repositories)  # type: list[Repository]
        self.source = {}

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

    def source_of(self, req):
        return self.source[req.name]
