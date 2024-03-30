"""req-compile Bazel integration test transitive dependencies"""

load("@req_compile_test_find_links//:defs.bzl", find_links_repositories = "repositories")

def test_dependencies_3():
    """req-compile Bazel integration test transitive dependencies"""
    find_links_repositories()
