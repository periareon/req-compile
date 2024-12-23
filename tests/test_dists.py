import logging
from typing import Any

import pkg_resources
import pytest
from pkg_resources import Requirement

from req_compile.containers import DistInfo
from req_compile.dists import (
    DistributionCollection,
    _get_cycle,
    _paths_to_self,
    build_explanation,
)


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


def test_base_plugin_circular_completed() -> None:
    """Create a root and plugin-style circular dependency and ensure that the graph is completed."""
    dists = DistributionCollection()
    metadata_root = DistInfo(
        "root",
        "1.0.0",
        reqs=pkg_resources.parse_requirements(["root-c", "root-a", "root-b"]),
    )
    metadata_root_a = DistInfo(
        "root-a", "1.0.0", reqs=pkg_resources.parse_requirements(["root", "dep-a"])
    )
    metadata_dep_a = DistInfo("dep-a", "1.0.0", reqs=[])
    metadata_root_b = DistInfo(
        "root-b",
        "1.0.0",
        reqs=pkg_resources.parse_requirements(["root", "dep-b", "common"]),
    )
    metadata_dep_b = DistInfo("dep-b", "1.0.0", reqs=[])
    metadata_root_c = DistInfo(
        "root-c", "1.0.0", reqs=pkg_resources.parse_requirements(["dep-c"])
    )
    metadata_dep_c = DistInfo("dep-c", "1.0.0", reqs=[])
    metadata_common = DistInfo(
        "common", "1.0.0", reqs=pkg_resources.parse_requirements(["root", "dep-a"])
    )

    root_node = dists.add_dist(metadata_root, None, Requirement.parse("root"))
    a_node = dists.add_dist(metadata_root_a, root_node, Requirement.parse("root-a"))
    dists.add_dist(metadata_dep_a, a_node, Requirement.parse("dep-a"))
    b_node = dists.add_dist(metadata_root_b, root_node, Requirement.parse("root-b"))
    dists.add_dist(metadata_dep_b, b_node, Requirement.parse("dep-b"))
    dists.add_dist(metadata_common, b_node, Requirement.parse("common"))
    dists.add_dist(metadata_dep_b, b_node, Requirement.parse("dep-b"))
    c_node = dists.add_dist(metadata_root_c, root_node, Requirement.parse("root-c"))
    dists.add_dist(metadata_dep_c, c_node, Requirement.parse("dep-c"))

    assert list(dists["root-c"].dependencies) == [dists["dep-c"]]
    assert list(dists["root-c"].reverse_deps) == [dists["root"]]

    assert set(dists["common"].dependencies) == {dists["root"], dists["dep-a"]}
    assert list(dists["common"].reverse_deps) == [dists["root-b"]]

    assert _get_cycle(dists["root"]) == {
        dists["root"],
        dists["root-a"],
        dists["root-b"],
        dists["common"],
    }
    assert _get_cycle(dists["dep-c"]) == set()

    for node in dists:
        assert node.complete, str(node)


@pytest.fixture
def result_graph() -> Any:
    class _ResultGraph:
        results = DistributionCollection()
        previous = None

        def add(self, req, deps, source=None):
            logging.getLogger("req_compile.dists").disabled = True
            req = pkg_resources.Requirement.parse(req)
            dist_info = DistInfo(
                req.project_name,
                req.specs[0][1],
                pkg_resources.parse_requirements(deps),
            )
            reason = None
            source = source or self.previous
            if source is not None and req.project_name in self.results:
                for dep in source.metadata.reqs:
                    if dep.project_name == req.project_name:
                        reason = dep
                        break
            self.previous = self.results.add_dist(dist_info, source, reason)
            return self.previous

        def build(self):
            logging.getLogger("req_compile.dists").disabled = False
            return self.results

        @property
        def complete(self):
            return all(dep.complete for dep in self.results)

    return _ResultGraph()

# pylint: disable=redefined-outer-name
def test_simple_cycle(result_graph):
    result_graph.add("a==1.0", ["b"])
    result_graph.add("b==1.0", ["a"])
    graph = result_graph.build()

    assert _get_cycle(graph["a"]) == {graph["b"], graph["a"]}
    assert _get_cycle(graph["b"]) == {graph["b"], graph["a"]}
    assert result_graph.complete


def test_triple_cycle(result_graph):
    result_graph.add("a==1.0", ["b"])
    result_graph.add("b==1.0", ["c"])
    result_graph.add("c==1.0", ["a"])
    graph = result_graph.build()

    assert _get_cycle(graph["a"]) == {graph["b"], graph["a"], graph["c"]}
    assert _get_cycle(graph["b"]) == {graph["b"], graph["a"], graph["c"]}
    assert _get_cycle(graph["c"]) == {graph["b"], graph["a"], graph["c"]}
    assert result_graph.complete


def test_quad_cycle(result_graph):
    result_graph.add("a==1.0", ["b"])
    result_graph.add("b==1.0", ["c"])
    result_graph.add("c==1.0", ["d"])
    result_graph.add("d==1.0", ["a"])
    graph = result_graph.build()

    assert (
        _get_cycle(graph["a"])
        == _get_cycle(graph["b"])
        == _get_cycle(graph["c"])
        == _get_cycle(graph["d"])
        == {graph["b"], graph["a"], graph["c"], graph["d"]}
    )
    assert result_graph.complete


def test_dual_cycle(result_graph):
    a = result_graph.add("a==1.0", ["b"])
    b = result_graph.add("b==1.0", ["a"])
    c = result_graph.add("c==1.0", ["a"], source=a)

    assert _get_cycle(a) == _get_cycle(b) == _get_cycle(c) == {a, b, c}
    assert result_graph.complete


def test_unrelated_dual(result_graph):
    a = result_graph.add("a==1.0", ["b", "x"])
    b = result_graph.add("b==1.0", ["a"])
    x = result_graph.add("x==1.0", [], source=a)
    c = result_graph.add("c==1.0", ["a"], source=a)

    assert set(x.dependencies) == set()

    assert _paths_to_self(a) == {a, b, c}
    assert _get_cycle(a) == _get_cycle(b) == _get_cycle(c) == {a, b, c}
    assert _get_cycle(x) == set()

    assert result_graph.complete


def test_root_not_cycle(result_graph) -> None:
    a = result_graph.add("a==1.0", ["b", "c"])
    b = result_graph.add("b==1.0", ["c"])
    c = result_graph.add("c==1.0", ["b"], source=a)
    result_graph.build()

    assert _get_cycle(a) == set()
    assert _paths_to_self(a) == set()
    assert _paths_to_self(b) == {b, c}
    assert _get_cycle(b) == _get_cycle(c) == {b, c}
