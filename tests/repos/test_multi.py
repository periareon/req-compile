import sys
from unittest import mock

import pkg_resources
import pytest

from req_compile.containers import DistInfo
from req_compile.errors import NoCandidateException
from req_compile.repos import Repository
from req_compile.repos.multi import MultiRepository
from req_compile.repos.repository import Candidate


class FakeRepository(Repository):
    def __init__(self, name):
        super(FakeRepository, self).__init__("test")
        self.name = name
        self.get_candidates = mock.MagicMock(side_effect=self._get_candidates)

    def __repr__(self):
        return self.name

    def __eq__(self, other):
        return (
            isinstance(other, FakeRepository)
            and super(FakeRepository, self).__eq__(other)
            and self.name == other.name
        )

    def __hash__(self):
        return hash("fakerepo") ^ hash(self.name)

    def get_candidates(self, req):
        pass

    def _get_candidates(self, req):
        raise NoCandidateException(req)

    def resolve_candidate(self, candidate):
        return DistInfo(candidate.name, candidate.version, []), False

    def close(self):
        pass


def test_nested_multi():
    """Verify that nested multirepositories are expanded"""
    repo1 = FakeRepository("1")
    multi1 = MultiRepository(repo1)

    repo2 = FakeRepository("2")

    repo3 = FakeRepository("3")
    repo4 = FakeRepository("4")
    multi2 = MultiRepository(repo3, repo4)

    final_multi = MultiRepository(repo2, multi1, multi2)

    assert list(final_multi) == [repo2, repo1, repo3, repo4]


def test_not_found():
    """Verify that if not found, NoCandidateException is raised"""
    repo1 = FakeRepository("1")
    multi1 = MultiRepository(repo1)
    with pytest.raises(NoCandidateException):
        multi1.get_dist(pkg_resources.Requirement("nonsense"))


def test_fetch_in_order():
    """Verify both repos are attempted"""
    repo1 = FakeRepository("1")
    repo2 = FakeRepository("2")
    repo3 = FakeRepository("3")

    repo3.get_candidates.side_effect = lambda req: [
        Candidate(
            "nonsense", ".", pkg_resources.parse_version("1.0"), None, None, "any", ""
        )
    ]
    multi = MultiRepository(repo1, repo2, repo3)

    result, _ = multi.get_dist(pkg_resources.Requirement("nonsense"))

    assert repo1.get_candidates.called
    assert repo2.get_candidates.called
    assert repo3.get_candidates.called

    assert result.version == pkg_resources.parse_version("1.0")

    candidates = multi.get_candidates(pkg_resources.Requirement("nonsense"))
    assert len(candidates) == 1
    assert candidates[0].name == "nonsense"
    assert candidates[0].version == pkg_resources.parse_version("1.0")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
