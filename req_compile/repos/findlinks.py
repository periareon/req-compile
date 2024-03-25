import os
from hashlib import sha256
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple, Union

import pkg_resources
from overrides import overrides

import req_compile.metadata
import req_compile.metadata.metadata
import req_compile.repos.repository
from req_compile import utils
from req_compile.containers import RequirementContainer
from req_compile.repos import Repository, RepositoryInitializationError
from req_compile.repos.repository import Candidate


def _relativize(from_path: Path, to_path: Path) -> Path:
    """Compute the relative path from one location to another.

    Unlike `pathlib.Path.relative_to`, this handles the case where a path
    is trying to traverse up to a parent.

    Args:
        from_path: The starting location
        to_path: The target location

    Returns:
        The relativized path
    """
    try:
        return to_path.relative_to(from_path)
    except ValueError:
        # In the event from_path is not a parent of to_path, we will
        # ignore the exception raised by `pathlib.Path.relative_to` and
        # instead try to manually find a common parent so the path up
        # to this location can be computed to then return the relative path.
        pass

    root = None
    for parent in from_path.parents:
        if parent in to_path.parents:
            root = parent
            break

    if not root:
        raise ValueError(f"{from_path} and {to_path} do not have a common parent")

    to_root = Path("../" * len(from_path.relative_to(root).parents))

    return to_root / to_path.relative_to(root)


class FindLinksRepository(Repository):
    """
    A directory on the filesystem as a source of distributions.
    """

    def __init__(
        self,
        path: Union[str, Path],
        allow_prerelease: Optional[bool] = None,
        relative_to: Optional[Union[str, Path]] = None,
    ) -> None:
        super().__init__("findlinks", allow_prerelease=allow_prerelease)
        self.path = str(path)
        self.relative_path = (
            _relativize(Path(relative_to), Path(self.path)) if relative_to else None
        )
        self.links: List[Candidate] = []
        self._find_all_links()

    def __repr__(self) -> str:
        return "--find-links {}".format(self.relative_path or self.path)

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
                (
                    str(self.relative_path) if self.relative_path else self.path,
                    os.path.join(self.relative_path or self.path, filename),
                ),
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
