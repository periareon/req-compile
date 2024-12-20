import pkg_resources
from pkg_resources import Requirement

from req_compile.containers import DistInfo
from req_compile.dists import DistributionCollection, build_explanation


def test_unconstrained():
    dists = DistributionCollection()
    dists.add_dist(
        DistInfo("aaa", "1.2.0", pkg_resources.parse_requirements(["bbb"])),
        None,
        Requirement.parse("aaa"),
    )
    assert dists["bbb"].build_constraints() == pkg_resources.Requirement.parse("bbb")
    assert len(dists) == 2
    assert not dists["aaa"].complete


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
    node = dists.add_dist(
        DistInfo("aaa", "1.2.0", pkg_resources.parse_requirements(["bbb<1.0"])),
        None,
        Requirement.parse("aaa"),
    )
    dists.remove_dists(node)
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
    assert dists["aaa"].complete


def test_unnormalized_dist_with_extra():
    dists = DistributionCollection()
    metadata = DistInfo("A", "1.0.0", [])

    dists.add_dist(metadata, None, Requirement.parse("A[x]"))

    assert dists["A"].metadata.version == "1.0.0"
    assert dists["A[x]"].metadata.version == "1.0.0"
    assert dists["A"].complete


def test_metadata_violated() -> None:
    dists = DistributionCollection()
    metadata_a = DistInfo("a", "1.0.0", [])

    dists.add_dist(metadata_a, None, None)
    dists.add_dist(metadata_a, None, Requirement.parse("a>1.0"))

    assert dists["a"].metadata is None
    assert dists["a"].dependencies == {}
    assert dists["a"].reverse_deps == set()
    assert not dists["a"].complete


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

    root = dists.add_dist(root, None, None)
    root_a = dists.add_dist(
        metadata_a, None, pkg_resources.Requirement.parse("a[test]")
    )
    dists.add_dist(
        metadata_b, root_a, pkg_resources.Requirement.parse('b ; extra=="test"')
    )
    dists.add_dist(metadata_c, root_a, pkg_resources.Requirement.parse("a"))

    results = [
        ("==".join(node.metadata.to_definition(node.extras)), build_explanation(node))
        for node in dists.visit_nodes({root})
    ]
    assert sorted(results) == [
        ("a[test]==1.0.0", ["root ([test])"]),
        ("b==2.0.0", ["a[test]"]),
        ("c==2.0.0", ["a"]),
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
    assert not dists["a"].complete
    assert not dists["b"].complete
    assert not dists["root"].complete


def test_circular_self_dep() -> None:
    """Test that a self edge is OK."""
    dists = DistributionCollection()
    metadata_a = DistInfo("a", "1.0.0", reqs=pkg_resources.parse_requirements(["a"]))

    dists.add_dist(metadata_a, None, None)

    assert dists["A"].metadata.version == "1.0.0"
    assert dists["A"].complete


def test_circular_self_invalidate() -> None:
    """Test that a self edge can invalidate correctly."""
    dists = DistributionCollection()
    metadata_a = DistInfo("a", "1.0.0", reqs=pkg_resources.parse_requirements(["a"]))

    dists.add_dist(metadata_a, None, None)
    dists.add_dist(metadata_a, None, Requirement.parse("a>1.0"))

    assert dists["a"].metadata is None
    assert dists["a"].dependencies == {}
    assert dists["a"].reverse_deps == set()
    assert not dists["a"].complete


def test_big_circular_invalidate() -> None:
    """Test that a two node circular dep can invalidate correctly."""
    dists = DistributionCollection()
    metadata_a = DistInfo("a", "1.0.0", reqs=pkg_resources.parse_requirements(["b"]))
    metadata_b = DistInfo("b", "1.0.0", reqs=pkg_resources.parse_requirements(["a"]))

    meta = dists.add_dist(
        DistInfo("-", None, pkg_resources.parse_requirements(["a", "b"]), meta=True),
        None,
        None,
    )

    dists.add_dist(metadata_a, meta, Requirement.parse("a"))
    dists.add_dist(metadata_b, meta, Requirement.parse("b"))

    for node in dists:
        print(node, node.complete)

    dists.add_dist(metadata_a, None, Requirement.parse("a>1.0"))

    assert dists["a"].metadata is None
    assert dists["a"].dependencies == {}
    assert dists["a"].reverse_deps == {dists["_"], dists["b"]}

    dists.add_dist(metadata_a, None, Requirement.parse("a<=1.0"))
    for node in dists:
        assert node.complete
