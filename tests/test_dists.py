import pkg_resources
from pkg_resources import Requirement

from req_compile.containers import DistInfo
from req_compile.dists import DistributionCollection


def test_unconstrained():
    dists = DistributionCollection()
    dists.add_dist(
        DistInfo("aaa", "1.2.0", pkg_resources.parse_requirements(["bbb"])),
        None,
        Requirement.parse("aaa"),
    )
    assert dists["bbb"].build_constraints() == pkg_resources.Requirement.parse("bbb")


def test_one_source():
    dists = DistributionCollection()
    dists.add_dist(
        DistInfo("aaa", "1.2.0", pkg_resources.parse_requirements(["bbb<1.0"])),
        None,
        Requirement.parse("aaa"),
    )
    assert dists["aaa"].build_constraints() == Requirement.parse("aaa")
    assert dists["bbb"].build_constraints() == Requirement.parse("bbb<1.0")


def test_two_sources():
    dists = DistributionCollection()
    dists.add_dist(
        DistInfo("aaa", "1.2.0", pkg_resources.parse_requirements(["bbb<1.0"])),
        None,
        Requirement.parse("aaa"),
    )
    dists.add_dist(
        DistInfo("ccc", "1.0.0", pkg_resources.parse_requirements(["bbb>0.5"])),
        None,
        Requirement.parse("ccc"),
    )
    assert dists["bbb"].build_constraints() == pkg_resources.Requirement.parse(
        "bbb>0.5,<1.0"
    )


def test_two_sources_same():
    dists = DistributionCollection()
    dists.add_dist(
        DistInfo("aaa", "1.2.0", pkg_resources.parse_requirements(["bbb<1.0"])),
        None,
        Requirement.parse("aaa"),
    )
    dists.add_dist(
        DistInfo("ccc", "1.0.0", pkg_resources.parse_requirements(["bbb<1.0"])),
        None,
        Requirement.parse("ccc"),
    )
    assert dists["bbb"].build_constraints() == pkg_resources.Requirement.parse(
        "bbb<1.0"
    )


def test_add_remove_dist():
    dists = DistributionCollection()
    nodes = dists.add_dist(
        DistInfo("aaa", "1.2.0", pkg_resources.parse_requirements(["bbb<1.0"])),
        None,
        Requirement.parse("aaa"),
    )
    assert len(nodes) == 1
    dists.remove_dists(nodes)
    assert "bbb" not in dists


def test_dist_with_unselected_extra():
    dists = DistributionCollection()
    dists.add_dist(
        DistInfo(
            "aaa",
            "1.2.0",
            reqs=pkg_resources.parse_requirements(['bbb<1.0 ; extra=="x1"']),
        ),
        None,
        None,
    )

    assert str(dists.nodes["aaa"].metadata) == "aaa==1.2.0"


def test_unnormalized_dist_with_extra():
    dists = DistributionCollection()
    metadata = DistInfo("A", "1.0.0", [])

    dists.add_dist(metadata, None, Requirement.parse("A[x]"))

    assert dists["A"].metadata.version == "1.0.0"
    assert dists["A[x]"].metadata.version == "1.0.0"


def test_metadata_violated():
    dists = DistributionCollection()
    metadata_a = DistInfo("a", "1.0.0", [])

    dists.add_dist(metadata_a, None, None)
    dists.add_dist(metadata_a, None, Requirement.parse("a>1.0"))

    assert dists.nodes["a"].metadata is None


def test_metadata_violated_removes_transitive():
    dists = DistributionCollection()
    metadata_a = DistInfo("a", "1.0.0", reqs=pkg_resources.parse_requirements(["b"]))

    dists.add_dist(metadata_a, None, None)
    dists.add_dist(metadata_a, None, Requirement.parse("a>1.0"))

    assert dists["a"].metadata is None
    assert "b" not in dists


def test_metadata_transitive_violated():
    dists = DistributionCollection()
    metadata_a = DistInfo("a", "1.0.0", [])
    metadata_b = DistInfo(
        "b", "1.0.0", reqs=pkg_resources.parse_requirements(["a>1.0"])
    )

    dists.add_dist(metadata_a, None, None)
    dists.add_dist(metadata_b, None, None)

    assert dists.nodes["a"].metadata is None


def test_repo_with_extra():
    dists = DistributionCollection()
    root = DistInfo(
        "root", "1.0", pkg_resources.parse_requirements(["a[test]"]), meta=True
    )
    metadata_a = DistInfo(
        "a", "1.0.0", pkg_resources.parse_requirements(['b ; extra=="test"', "c"])
    )
    metadata_b = DistInfo("b", "2.0.0", [])
    metadata_c = DistInfo("c", "2.0.0", [])

    root = next(iter(dists.add_dist(root, None, None)))
    root_a = next(
        iter(
            dists.add_dist(metadata_a, None, pkg_resources.Requirement.parse("a[test]"))
        )
    )
    dists.add_dist(
        metadata_b, root_a, pkg_resources.Requirement.parse('b ; extra=="test"')
    )
    dists.add_dist(metadata_c, root_a, pkg_resources.Requirement.parse("a"))

    lines = dists.generate_lines({root})
    assert sorted(lines) == [
        (("a[test]", "1.0.0", None), "root"),
        (("b", "2.0.0", None), "a[test]"),
        (("c", "2.0.0", None), "a"),
    ]


def test_regular_and_extra_constraints():
    dists = DistributionCollection()
    root = DistInfo(
        "root", "1.0", pkg_resources.parse_requirements(["a[test]"]), meta=True
    )
    metadata_a = DistInfo(
        "a", "1.0.0", pkg_resources.parse_requirements(['b>3 ; extra=="test"', "b>2"])
    )

    dists.add_dist(root, None, None)
    dists.add_dist(metadata_a, None, pkg_resources.Requirement.parse("a[test]"))

    assert dists["b"].build_constraints() == pkg_resources.Requirement.parse("b>2,>3")
