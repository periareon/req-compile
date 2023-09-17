import itertools
from typing import Iterable, Iterator, List, Optional, Tuple

import pkg_resources
from overrides import overrides

from req_compile.containers import RequirementContainer
from req_compile.errors import NoCandidateException
from req_compile.repos.repository import Candidate, Repository


class MultiRepository(Repository):
    """Repository that sources from inner repositories, in order."""

    def __init__(self, *repositories: Repository) -> None:
        """Constructor."""
        super(MultiRepository, self).__init__("multi")
        self.repositories = list(repositories)

    def __repr__(self) -> str:
        return ", ".join(repr(repo) for repo in self)

    def __iter__(self) -> Iterator[Repository]:
        # Expand nested MultiRepositories as well
        return itertools.chain(*(iter(repo) for repo in self.repositories))

    def __hash__(self) -> int:
        return hash(self.repositories)

    @overrides
    def get_candidates(
        self, req: Optional[pkg_resources.Requirement]
    ) -> Iterable[Candidate]:
        candidates: List[Candidate] = []
        for idx, repo in enumerate(self.repositories):
            try:
                repo_candidates = repo.get_candidates(req)
                for candidate in repo_candidates:
                    candidate.source = repo
                    # Make sure we consider earlier repos in this list first if
                    # equally-scoring candidates are provided.
                    candidate.extra_sort_info = (idx, candidate.extra_sort_info)
                candidates.extend(repo_candidates)
            except NoCandidateException:
                pass
        return candidates

    @overrides
    def resolve_candidate(
        self, candidate: Candidate
    ) -> Tuple[RequirementContainer, bool]:
        assert candidate.source is not None
        return candidate.source.resolve_candidate(candidate)

    @overrides
    def close(self) -> None:
        pass
