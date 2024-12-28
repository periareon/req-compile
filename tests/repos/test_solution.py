# pylint: disable=redefined-outer-name,unused-argument
# pylint: disable=protected-access
import os
from io import StringIO
from pathlib import Path
import sys
from textwrap import dedent

import pkg_resources
import pytest

import req_compile.compile
from req_compile.cmdline import write_requirements_file
from req_compile.containers import DistInfo
from req_compile.repos import RepositoryInitializationError
from req_compile.repos.findlinks import FindLinksRepository
from req_compile.repos.multi import MultiRepository
from req_compile.repos.pypi import IndexType, PyPIRepository
from req_compile.repos.solution import SolutionRepository
from req_compile.utils import parse_requirement, parse_version

TEST_DIR = os.path.dirname(__file__)


def test_solution_repo():
    solution_repo = SolutionRepository(os.path.join(TEST_DIR, "solutionfile.txt"))
    result, cached = solution_repo.get_dist(pkg_resources.Requirement.parse("pylint"))
    assert result.version == pkg_resources.parse_version("1.9.4")
    assert cached


def _get_node_strs(nodes):
    return set(node.key for node in nodes)


def test_load_bad_solution(load_solution):
    with pytest.raises(RepositoryInitializationError):
        load_solution(os.path.join(TEST_DIR, "bad_solutionfile.txt"))


def test_load_solution(load_solution):
    result = load_solution(os.path.join(TEST_DIR, "solutionfile.txt"))

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


def test_load_solution_excluded():
    repo = SolutionRepository(
        os.path.join(TEST_DIR, "solutionfile.txt"), excluded_packages=["mccabe"]
    )
    result = repo.get_candidates(pkg_resources.Requirement.parse("mccabe"))
    assert result == []


def test_load_solution_excluded_normalized():
    repo = SolutionRepository(
        os.path.join(TEST_DIR, "solutionfile.txt"),
        excluded_packages=["lazy_object_proxy"],
    )
    result = repo.get_candidates(pkg_resources.Requirement.parse("lazy-object-proxy"))
    assert result == []


def test_load_solution_extras(load_solution):
    result = load_solution(os.path.join(TEST_DIR, "solutionfile_extras.txt"))

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
    result = load_solution(os.path.join(TEST_DIR, "solutionfile_extras.txt"))

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
    result = load_solution(os.path.join(TEST_DIR, "solutionfile_fuzzywuzzy_extras.txt"))

    assert _get_node_strs(result["python-Levenshtein"].reverse_deps) == {"fuzzywuzzy"}

    assert set(result["fuzzywuzzy"].metadata.requires()) == set()
    assert set(result["fuzzywuzzy"].metadata.requires("speedup")) == {
        pkg_resources.Requirement.parse('python-Levenshtein>=0.12 ; extra=="speedup"'),
    }


def test_load_solution_urls(load_solution):
    """Test that URLs can be loaded properly from solutions."""
    result = load_solution(os.path.join(TEST_DIR, "solutionfile_urls.txt"))

    assert (
        result["pylint"].metadata.candidate.link[1]
        # pylint: disable-next=line-too-long
        == "https://files.pythonhosted.org/packages/63/cc/00cbe3f09bd6d98d79ee66cf76451d253fb1a8a59029535ea2b6ba8a824d/pylint-2.17.5-py3-none-any.whl#sha256=73995fb8216d3bed149c8d51bba25b2c52a8251a2c8ac846ec668ce38fab5413"
    )


def test_load_remove_root_removes_all(load_solution):
    result = load_solution(os.path.join(TEST_DIR, "solutionfile.txt"))

    result.remove_dists(result["pylint"])

    assert len(result.nodes) == 0


@pytest.mark.parametrize(
    "scenario, roots",
    [
        ("normal", ["a", "d"]),
        ("normal", ["a[x1]"]),
    ],
)
@pytest.mark.parametrize("multiline", [True, False])
@pytest.mark.parametrize("hashes", [True, False])
def test_round_trip(
    scenario, roots, mock_metadata, multiline, hashes, mock_pypi, tmp_path
):
    mock_pypi.load_scenario(scenario)

    results, nodes = req_compile.compile.perform_compile(
        [DistInfo("test", None, pkg_resources.parse_requirements(roots), meta=True)],
        mock_pypi,
    )

    solution_path = tmp_path / "solution.txt"
    with solution_path.open("w", encoding="utf-8") as fh:
        write_requirements_file(
            results,
            nodes,
            repo=mock_pypi,
            hashes=hashes,
            multiline=multiline,
            write_to=fh,
        )

    # Make some assertions about what the solution file looks like
    # to ensure we're testing the right things.
    with solution_path.open("r") as fh:
        contents = fh.read()
        if hashes:
            assert "--hash" in contents
            if multiline:
                assert "\\" in contents
        else:
            if multiline:
                assert "via" in contents

    solution_result = SolutionRepository(solution_path)
    for node in results:
        if isinstance(node.metadata, DistInfo) and node.key != "test":
            assert node.key in solution_result.solution


def test_writing_repo_sources(mock_metadata, mock_pypi, tmp_path):
    mock_pypi.load_scenario("normal")

    results, nodes = req_compile.compile.perform_compile(
        [DistInfo("foo", None, pkg_resources.parse_requirements(["a"]), meta=True)],
        mock_pypi,
    )

    links_path = Path(tmp_path)

    buffer = StringIO()
    write_requirements_file(
        results,
        set(nodes),
        repo=MultiRepository(
            [
                mock_pypi,
                FindLinksRepository(path=links_path),
                PyPIRepository(
                    index_url="https://index.com",
                    wheeldir=tmp_path,
                    index_type=IndexType.INDEX_URL,
                ),
                PyPIRepository(
                    index_url="https://extra.com",
                    wheeldir=tmp_path,
                    index_type=IndexType.EXTRA_INDEX_URL,
                ),
            ]
        ),
        write_to=buffer,
    )

    header = dedent(
        f"""\
        --index-url https://index.com
        --extra-index-url https://extra.com
        --find-links {links_path.as_posix()}
        """
    ).strip()
    assert header in buffer.getvalue()


def test_load_additive_constraints():
    """Test that solutions with additive constraints, where extras add an extra constraint
    to an existing requirement, are reconstructed correctly"""
    solution_repo = SolutionRepository(
        os.path.join(os.path.dirname(__file__), "requests_security_solution.txt")
    )
    constraints = solution_repo.solution["idna"].build_constraints()
    assert constraints == pkg_resources.Requirement.parse("idna<2.9,>=2.5")


def test_load_extras() -> None:
    """Test that if the correct extras are associated with the correct requirements."""
    solution_repo = SolutionRepository(
        os.path.join(os.path.dirname(__file__), "requests_kerberos_solution.txt")
    )
    assert solution_repo.solution["pyspnego"].extras == {"kerberos"}
    assert [
        req
        for req in solution_repo.solution["requests-kerberos"].metadata.requires(None)
        if req.project_name == "pyspnego"
    ][0] == parse_requirement("pyspnego[kerberos]>=0.9.2")


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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
