import os
import tempfile

import pkg_resources
import pytest

import req_compile.compile
from req_compile.containers import DistInfo
from req_compile.repos import RepositoryInitializationError
from req_compile.repos.solution import SolutionRepository
from req_compile.utils import parse_requirement, parse_version


def test_solution_repo():
    solution_repo = SolutionRepository(
        os.path.join(os.path.dirname(__file__), "..", "solutionfile.txt")
    )
    result, cached = solution_repo.get_dist(pkg_resources.Requirement.parse("pylint"))
    assert result.version == pkg_resources.parse_version("1.9.4")
    assert cached


def _get_node_strs(nodes):
    return set(node.key for node in nodes)


def test_load_bad_solution(load_solution):
    with pytest.raises(RepositoryInitializationError):
        load_solution("bad_solutionfile.txt")


def test_load_solution(load_solution):
    result = load_solution("solutionfile.txt")

    assert _get_node_strs(result["six"].reverse_deps) == {"astroid", "pylint"}
    assert _get_node_strs(result["astroid"].reverse_deps) == {"pylint"}
    assert _get_node_strs(result["pylint"].reverse_deps) == set()

    assert set(result["pylint"].metadata.reqs) == {
        pkg_resources.Requirement.parse("six"),
        pkg_resources.Requirement.parse("colorama"),
        pkg_resources.Requirement.parse("astroid>=1.6,<2.0"),
        pkg_resources.Requirement.parse("mccabe"),
        pkg_resources.Requirement.parse("isort>=4.2.5"),
    }

    assert set(result["astroid"].metadata.requires()) == {
        pkg_resources.Requirement.parse("six"),
        pkg_resources.Requirement.parse("lazy-object-proxy"),
        pkg_resources.Requirement.parse("wrapt"),
    }


def test_load_solution_excluded(load_solution):
    repo = SolutionRepository("solutionfile.txt", excluded_packages=["mccabe"])
    result = repo.get_candidates(pkg_resources.Requirement.parse("mccabe"))
    assert result == []


def test_load_solution_excluded_normalized(load_solution):
    repo = SolutionRepository(
        "solutionfile.txt", excluded_packages=["lazy_object_proxy"]
    )
    result = repo.get_candidates(pkg_resources.Requirement.parse("lazy-object-proxy"))
    assert result == []


def test_load_solution_extras(load_solution):
    result = load_solution("solutionfile_extras.txt")

    # a == 1.0  # inputfile.txt
    # docpkg == 2.0  # a[docs] (>1.0), b
    # pytest == 4.0  # a[test]
    # b == 1.0  # a (1.0)
    assert set(result["a"].metadata.reqs) == set(
        pkg_resources.parse_requirements(
            ['docpkg>1.0 ; extra == "docs"', 'pytest ; extra == "test"', "b==1.0"]
        )
    )


def test_load_solution_extras_not_on_req(load_solution):
    result = load_solution("solutionfile_extras.txt")

    # a[docs, test] == 1.0  # inputfile.txt
    # docpkg == 2.0  # a[docs] (>1.0), b
    # pytest == 4.0  # a[test]
    # b == 1.0  # a (1.0)
    assert set(result["a"].metadata.reqs) == set(
        pkg_resources.parse_requirements(
            ['docpkg>1.0 ; extra == "docs"', 'pytest ; extra == "test"', "b==1.0"]
        )
    )


def test_load_solution_fuzzywuzzy_extras(load_solution):
    result = load_solution("solutionfile_fuzzywuzzy_extras.txt")

    assert _get_node_strs(result["python-Levenshtein"].reverse_deps) == {"fuzzywuzzy"}

    assert set(result["fuzzywuzzy"].metadata.requires()) == set()
    assert set(result["fuzzywuzzy"].metadata.requires("speedup")) == {
        pkg_resources.Requirement.parse('python-Levenshtein>=0.12 ; extra=="speedup"'),
    }


def test_load_remove_root_removes_all(load_solution):
    result = load_solution("solutionfile.txt")

    result.remove_dists(result["pylint"])

    assert len(result.nodes) == 0


@pytest.mark.parametrize(
    "scenario, roots",
    [
        ("normal", ["a", "d"]),
        ("normal", ["a[x1]"]),
    ],
)
def test_round_trip(scenario, roots, mock_metadata, mock_pypi):
    mock_pypi.load_scenario("normal")

    results, nodes = req_compile.compile.perform_compile(
        [DistInfo("test", None, pkg_resources.parse_requirements(roots), meta=True)],
        mock_pypi,
    )

    fd, name = tempfile.mkstemp()
    for line in results.generate_lines(nodes):
        print("{}=={}  # {}".format(line[0][0], line[0][1], line[1]))
        os.write(
            fd, "{}=={}  # {}\n".format(line[0][0], line[0][1], line[1]).encode("utf-8")
        )
    os.close(fd)

    solution_result = SolutionRepository(name)
    for node in results:
        if isinstance(node.metadata, DistInfo) and node.key != "test":
            assert node.key in solution_result.solution


def test_load_additive_constraints():
    """Test that solutions with additive constraints, where extras add an extra constraint
    to an existing requirement, are reconstructed correctly"""
    solution_repo = SolutionRepository(
        os.path.join(os.path.dirname(__file__), "requests_security_solution.txt")
    )
    constraints = solution_repo.solution["idna"].build_constraints()
    assert constraints == pkg_resources.Requirement.parse("idna<2.9,>=2.5")


def test_load_extra_first():
    """Test that solutions that refer to a requirement with an extra before it is defined correctly
    add the requirement with the extra"""
    solution_repo = SolutionRepository(
        os.path.join(os.path.dirname(__file__), "extra_only_solution.txt")
    )
    assert solution_repo.solution["extra_only"].metadata.name == "extra_only"

    solution_repo = SolutionRepository(
        os.path.join(os.path.dirname(__file__), "extra_only_solution_no_extras.txt")
    )
    assert solution_repo.solution["extra_only"].metadata.name == "extra_only"


def test_simple_inline_solution():
    solution_repo = SolutionRepository("garbage.txt.test")
    solution_repo._load_from_lines(["myreq==34 # -\n", "child_req==1 # myreq\n"])

    dist = solution_repo.get_dist(parse_requirement("myreq"))[0]
    assert dist.version == parse_version("34")
    assert set(dist.reqs) == {parse_requirement("child_req")}


def test_simple_multiline_solution():
    solution_repo = SolutionRepository("garbage.txt.test")
    solution_repo._load_from_lines(
        ["myreq==34\n", "    # via -\n", "child_req==1\n", "    # via myreq\n"]
    )

    dist = solution_repo.get_dist(parse_requirement("myreq"))[0]
    assert dist.version == parse_version("34")
    assert set(dist.reqs) == {parse_requirement("child_req")}


def test_load_single_line_hash():
    """Check that the --hash option is parsed and included in the solution."""
    solution_repo = SolutionRepository("garbage.txt.test")
    solution_repo._load_from_lines(["myreq==34 --hash=myhash:1234  # -\n"])

    assert solution_repo.solution["myreq"].metadata.hash == "myhash:1234"


def test_load_multi_line_hash():
    """Check that the hash can be on the next line."""
    solution_repo = SolutionRepository("garbage.txt.test")
    solution_repo._load_from_lines(
        ["myreq==34 \\\n", "    --hash=myhash:567\n", "    # via -\n"]
    )

    assert solution_repo.solution["myreq"].metadata.hash == "myhash:567"
