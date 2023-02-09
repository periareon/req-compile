import os
from hashlib import sha256
from typing import Any, List, Optional, Sequence, Tuple

import pkg_resources
from overrides import overrides

import req_compile.metadata
import req_compile.metadata.metadata
import req_compile.repos.repository
from req_compile import utils
from req_compile.containers import RequirementContainer
from req_compile.repos import Repository, RepositoryInitializationError
from req_compile.repos.repository import Candidate


class FindLinksRepository(Repository):
    """
    A directory on the filesystem as a source of distributions.
    """

    def __init__(self, path: str, allow_prerelease: bool = None) -> None:
        super(FindLinksRepository, self).__init__(
            "findlinks", allow_prerelease=allow_prerelease
        )
        self.path = path
        self.links: List[Candidate] = []
        self._find_all_links()

    def __repr__(self) -> str:
        return "--find-links {}".format(self.path)

    def __eq__(self, other: Any) -> bool:
        return (
            isinstance(other, FindLinksRepository)
            and super(FindLinksRepository, self).__eq__(other)
            and self.path == other.path
        )

    def __hash__(self) -> int:
        return hash("findlinks") ^ hash(self.path)

    def _find_all_links(self) -> None:
        if not os.path.exists(self.path):
            raise RepositoryInitializationError(
                FindLinksRepository, "Directory {} not found.".format(self.path)
            )
        for filename in os.listdir(self.path):
            full_path = os.path.join(self.path, filename)
            candidate = req_compile.repos.repository.filename_to_candidate(
                (self.path, full_path),
                full_path,
            )
            if candidate is not None:
                self.links.append(candidate)

    @overrides
    def get_candidates(
        self, req: Optional[pkg_resources.Requirement]
    ) -> Sequence[Candidate]:
        project_name = None
        if req is not None:
            project_name = utils.normalize_project_name(req.project_name)
        results = []
        for candidate in self.links:
            if (
                req is None
                or utils.normalize_project_name(candidate.name) == project_name
            ):
                results.append(candidate)

        return results

    @overrides
    def resolve_candidate(
        self, candidate: Candidate
    ) -> Tuple[RequirementContainer, bool]:
        if candidate.filename is None:
            raise ValueError("Candidate not found on disk: {}".format(candidate))

        filename = os.path.join(self.path, candidate.filename)
        hasher = sha256()
        dist_info = req_compile.metadata.extract_metadata(filename, origin=self)
        with open(filename, "rb") as handle:
            while True:
                block = handle.read(4096)
                if not block:
                    break
                hasher.update(block)
        dist_info.hash = "sha256:" + hasher.hexdigest()
        return (
            dist_info,
            True,
        )

    @overrides
    def close(self) -> None:
        pass
