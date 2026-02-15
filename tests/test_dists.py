import logging
from typing import Any

import pytest
from packaging.requirements import Requirement

import req_compile.utils
from req_compile.containers import DistInfo
from req_compile.dists import (
    DependencyNode,
    DistributionCollection,
    _get_cycle,
    build_explanation,
)


def test_unconstrained():
    """Verifies an unconstrained transitive dependency keeps a bare requirement."""
    dists = DistributionCollection()
    dists.add_dist(
        DistInfo("aaa", "1.2.0", list(req_compile.utils.parse_requirements(["bbb"]))),
        None,
        Requirement("aaa"),
    )
    assert dists["bbb"].build_constraints() == Requirement("bbb")
    assert len(dists) == 2
    assert not dists["aaa"].complete


def test_one_source():
    """Verifies one reverse dependency contributes its single version constraint."""
    dists = DistributionCollection()
    dists.add_dist(
        DistInfo("aaa", "1.2.0", list(req_compile.utils.parse_requirements(["bbb<1.0"]))),
        None,
        Requirement("aaa"),
    )
    assert dists["aaa"].build_constraints() == Requirement("aaa")
    assert dists["bbb"].build_constraints() == Requirement("bbb<1.0")


def test_two_sources():
    """Verifies constraints from two sources are merged on the shared dependency."""
    dists = DistributionCollection()
    dists.add_dist(
        DistInfo("aaa", "1.2.0", list(req_compile.utils.parse_requirements(["bbb<1.0"]))),
        None,
        Requirement("aaa"),
    )
    dists.add_dist(
        DistInfo("ccc", "1.0.0", list(req_compile.utils.parse_requirements(["bbb>0.5"]))),
        None,
        Requirement("ccc"),
    )
    assert dists["bbb"].build_constraints() == Requirement(
        "bbb>0.5,<1.0"
    )


def test_two_sources_same():
    """Verifies duplicate constraints from multiple sources are de-duplicated."""
    dists = DistributionCollection()
    dists.add_dist(
        DistInfo("aaa", "1.2.0", list(req_compile.utils.parse_requirements(["bbb<1.0"]))),
        None,
        Requirement("aaa"),
    )
    dists.add_dist(
        DistInfo("ccc", "1.0.0", list(req_compile.utils.parse_requirements(["bbb<1.0"]))),
        None,
        Requirement("ccc"),
    )
    assert dists["bbb"].build_constraints() == Requirement(
        "bbb<1.0"
    )


def test_add_remove_dist():
    """Verifies removing a node also removes its orphaned transitive dependency."""
    dists = DistributionCollection()
    node = dists.add_dist(
        DistInfo("aaa", "1.2.0", list(req_compile.utils.parse_requirements(["bbb<1.0"]))),
        None,
        Requirement("aaa"),
    )
    dists.remove_dists(node)
    assert "bbb" not in dists


def test_dist_with_unselected_extra():
    """Verifies extra-only requirements are ignored when the extra is not requested."""
    dists = DistributionCollection()
    dists.add_dist(
        DistInfo(
            "aaa",
            "1.2.0",
            reqs=list(req_compile.utils.parse_requirements(['bbb<1.0 ; extra=="x1"'])),
        ),
        None,
        None,
    )

    assert str(dists.nodes["aaa"].metadata) == "aaa==1.2.0"
    assert dists["aaa"].complete


def test_unnormalized_dist_with_extra():
    """Verifies normalized and unnormalized package names resolve to one solved node."""
    dists = DistributionCollection()
    metadata = DistInfo("A", "1.0.0", [])

    dists.add_dist(metadata, None, Requirement("A[x]"))

    assert dists["A"].metadata.version == "1.0.0"
    assert dists["A[x]"].metadata.version == "1.0.0"
    assert dists["A"].complete


def test_metadata_violated() -> None:
    """Verifies a conflicting requirement invalidates metadata and clears solved state."""
    dists = DistributionCollection()
    metadata_a = DistInfo("a", "1.0.0", [])

    dists.add_dist(metadata_a, None, None)
    dists.add_dist(metadata_a, None, Requirement("a>1.0"))

    assert dists["a"].metadata is None
    assert dists["a"].dependencies == {}
    assert dists["a"].reverse_deps == set()
    assert not dists["a"].complete


def test_metadata_violated_removes_transitive():
    """Verifies metadata invalidation removes transitive nodes with no remaining parents."""
    dists = DistributionCollection()
    metadata_a = DistInfo("a", "1.0.0", reqs=list(req_compile.utils.parse_requirements(["b"])))

    dists.add_dist(metadata_a, None, None)
    dists.add_dist(metadata_a, None, Requirement("a>1.0"))

    assert dists["a"].metadata is None
    assert "b" not in dists


def test_metadata_transitive_violated():
    """Verifies a transitive conflict can invalidate an already solved dependency."""
    dists = DistributionCollection()
    metadata_a = DistInfo("a", "1.0.0", [])
    metadata_b = DistInfo(
        "b", "1.0.0", reqs=list(req_compile.utils.parse_requirements(["a>1.0"]))
    )

    dists.add_dist(metadata_a, None, None)
    dists.add_dist(metadata_b, None, None)

    assert dists.nodes["a"].metadata is None


def test_repo_with_extra():
    """Verifies explanations include extra-triggered and regular dependency reasons."""
    dists = DistributionCollection()
    root = DistInfo(
        "root", "1.0", list(req_compile.utils.parse_requirements(["a[test]"])), meta=True
    )
    metadata_a = DistInfo(
        "a", "1.0.0", list(req_compile.utils.parse_requirements(['b ; extra=="test"', "c"]))
    )
    metadata_b = DistInfo("b", "2.0.0", [])
    metadata_c = DistInfo("c", "2.0.0", [])

    root = dists.add_dist(root, None, None)
    root_a = dists.add_dist(
        metadata_a, None, Requirement("a[test]")
    )
    dists.add_dist(
        metadata_b, root_a, Requirement('b ; extra=="test"')
    )
    dists.add_dist(metadata_c, root_a, Requirement("a"))

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
    """Verifies regular and extra constraints are both applied to the same dependency."""
    dists = DistributionCollection()
    root = DistInfo(
        "root", "1.0", list(req_compile.utils.parse_requirements(["a[test]"])), meta=True
    )
    metadata_a = DistInfo(
        "a", "1.0.0", list(req_compile.utils.parse_requirements(['b>3 ; extra=="test"', "b>2"]))
    )

    dists.add_dist(root, None, None)
    dists.add_dist(metadata_a, None, Requirement("a[test]"))

    assert dists["b"].build_constraints() == Requirement("b>2,>3")
    assert not dists["a"].complete
    assert not dists["b"].complete
    assert not dists["root"].complete


def test_circular_self_dep() -> None:
    """Verifies a self-dependency is treated as a valid solved cycle."""
    dists = DistributionCollection()
    metadata_a = DistInfo("a", "1.0.0", reqs=list(req_compile.utils.parse_requirements(["a"])))

    dists.add_dist(metadata_a, None, None)

    assert dists["A"].metadata.version == "1.0.0"
    assert dists["A"].complete


def test_circular_self_invalidate() -> None:
    """Verifies a self-cycle is invalidated when a conflicting requirement is added."""
    dists = DistributionCollection()
    metadata_a = DistInfo("a", "1.0.0", reqs=list(req_compile.utils.parse_requirements(["a"])))

    dists.add_dist(metadata_a, None, None)
    dists.add_dist(metadata_a, None, Requirement("a>1.0"))

    assert dists["a"].metadata is None
    assert dists["a"].dependencies == {}
    assert dists["a"].reverse_deps == set()
    assert not dists["a"].complete


def test_big_circular_invalidate() -> None:
    """Verifies a two-node cycle invalidates and can be restored after constraints change."""
    dists = DistributionCollection()
    metadata_a = DistInfo("a", "1.0.0", reqs=list(req_compile.utils.parse_requirements(["b"])))
    metadata_b = DistInfo("b", "1.0.0", reqs=list(req_compile.utils.parse_requirements(["a"])))

    meta = dists.add_dist(
        DistInfo("-", None, list(req_compile.utils.parse_requirements(["a", "b"])), meta=True),
        None,
        None,
    )

    dists.add_dist(metadata_a, meta, Requirement("a"))
    dists.add_dist(metadata_b, meta, Requirement("b"))

    for node in dists:
        print(node, node.complete)

    dists.add_dist(metadata_a, None, Requirement("a>1.0"))

    assert dists["a"].metadata is None
    assert dists["a"].dependencies == {}
    assert dists["a"].reverse_deps == {dists["_"], dists["b"]}

    dists.add_dist(metadata_a, None, Requirement("a<=1.0"))
    for node in dists:
        assert node.complete


def test_base_plugin_circular_completed() -> None:
    """Verifies a mixed cyclic/acyclic plugin-style graph reaches complete state."""
    dists = DistributionCollection()
    metadata_root = DistInfo(
        "root",
        "1.0.0",
        reqs=list(req_compile.utils.parse_requirements(["root-c", "root-a", "root-b"])),
    )
    metadata_root_a = DistInfo(
        "root-a", "1.0.0", reqs=list(req_compile.utils.parse_requirements(["root", "dep-a"]))
    )
    metadata_dep_a = DistInfo("dep-a", "1.0.0", reqs=[])
    metadata_root_b = DistInfo(
        "root-b",
        "1.0.0",
        reqs=list(req_compile.utils.parse_requirements(["root", "dep-b", "common"])),
    )
    metadata_dep_b = DistInfo("dep-b", "1.0.0", reqs=[])
    metadata_root_c = DistInfo(
        "root-c", "1.0.0", reqs=list(req_compile.utils.parse_requirements(["dep-c"]))
    )
    metadata_dep_c = DistInfo("dep-c", "1.0.0", reqs=[])
    metadata_common = DistInfo(
        "common", "1.0.0", reqs=list(req_compile.utils.parse_requirements(["root", "dep-a"]))
    )

    root_node = dists.add_dist(metadata_root, None, Requirement("root"))
    a_node = dists.add_dist(metadata_root_a, root_node, Requirement("root-a"))
    dists.add_dist(metadata_dep_a, a_node, Requirement("dep-a"))
    b_node = dists.add_dist(metadata_root_b, root_node, Requirement("root-b"))
    dists.add_dist(metadata_dep_b, b_node, Requirement("dep-b"))
    dists.add_dist(metadata_common, b_node, Requirement("common"))
    dists.add_dist(metadata_dep_b, b_node, Requirement("dep-b"))
    c_node = dists.add_dist(metadata_root_c, root_node, Requirement("root-c"))
    dists.add_dist(metadata_dep_c, c_node, Requirement("dep-c"))

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
    """Builds a small helper for constructing dependency graphs incrementally in tests."""
    class _ResultGraph:
        results = DistributionCollection()
        previous = None

        def add(self, req, deps, source=None):
            logging.getLogger("req_compile.dists").disabled = True
            req = Requirement(req)
            dist_info = DistInfo(
                req.name,
                next(iter(req.specifier)).version,
                list(req_compile.utils.parse_requirements(deps)),
            )
            reason = None
            source = source or self.previous
            if source is not None and req.name in self.results:
                for dep in source.metadata.reqs:
                    if dep.name == req.name:
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
    """Verifies cycle detection and completeness for a two-node mutual dependency."""
    result_graph.add("a==1.0", ["b"])
    result_graph.add("b==1.0", ["a"])
    graph = result_graph.build()

    assert _get_cycle(graph["a"]) == {graph["b"], graph["a"]}
    assert _get_cycle(graph["b"]) == {graph["b"], graph["a"]}
    assert result_graph.complete


def test_triple_cycle(result_graph):
    """Verifies cycle detection and completeness for a three-node directed cycle."""
    result_graph.add("a==1.0", ["b"])
    result_graph.add("b==1.0", ["c"])
    result_graph.add("c==1.0", ["a"])
    graph = result_graph.build()

    assert _get_cycle(graph["a"]) == {graph["b"], graph["a"], graph["c"]}
    assert _get_cycle(graph["b"]) == {graph["b"], graph["a"], graph["c"]}
    assert _get_cycle(graph["c"]) == {graph["b"], graph["a"], graph["c"]}
    assert result_graph.complete


def test_quad_cycle(result_graph):
    """Verifies all nodes in a four-node cycle report the same cycle membership."""
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
    """Verifies a node linked into a cycle is included in the detected cycle set."""
    a = result_graph.add("a==1.0", ["b"])
    b = result_graph.add("b==1.0", ["a"])
    c = result_graph.add("c==1.0", ["a"], source=a)

    assert _get_cycle(a) == _get_cycle(b) == _get_cycle(c) == {a, b, c}
    assert result_graph.complete


def test_unrelated_dual(result_graph):
    """Verifies nodes outside the cycle are excluded while cycle members are included."""
    a = result_graph.add("a==1.0", ["b", "x"])
    b = result_graph.add("b==1.0", ["a"])
    x = result_graph.add("x==1.0", [], source=a)
    c = result_graph.add("c==1.0", ["a"], source=a)

    assert set(x.dependencies) == set()

    assert _get_cycle(a) == _get_cycle(b) == _get_cycle(c) == {a, b, c}
    assert _get_cycle(x) == set()

    assert result_graph.complete


def test_root_not_cycle(result_graph) -> None:
    """Verifies a root that points to a cycle is not itself treated as part of it."""
    a = result_graph.add("a==1.0", ["b", "c"])
    b = result_graph.add("b==1.0", ["c"])
    c = result_graph.add("c==1.0", ["b"], source=a)
    result_graph.build()

    assert _get_cycle(a) == set()
    assert _get_cycle(b) == _get_cycle(c) == {b, c}


def test_get_cycle_deep_acyclic_graph_no_recursion_error() -> None:
    """Verifies cycle detection handles deep acyclic chains without recursion issues."""
    nodes = [DependencyNode(f"n{i}", DistInfo(f"n{i}", "1.0.0", [])) for i in range(2000)]
    for idx in range(len(nodes) - 1):
        nodes[idx].add_reason(nodes[idx + 1], None)

    assert _get_cycle(nodes[0]) == set()


def test_get_cycle_ignores_unsolved_nodes() -> None:
    """Verifies cycle detection ignores edges through unsolved (`metadata is None`) nodes."""
    solved = DependencyNode("a", DistInfo("a", "1.0.0", []))
    unsolved = DependencyNode("b", None)

    solved.add_reason(unsolved, None)
    unsolved.add_reason(solved, None)

    assert _get_cycle(solved) == set()
