"""req-compile Bazel integration test transitive dependencies"""

load("@req_compile_test_find_links//:defs.bzl", find_links_repositories = "repositories")
load("@req_compile_test_sdist//:defs.bzl", sdist_repositories = "repositories")
load("@req_compile_test_simple//:defs.bzl", simple_repositories = "repositories")
load("@req_compile_test_transitive_ins//:defs.bzl", transitive_ins_repositories = "repositories")

def test_transitive_dependencies():
    """req-compile Bazel integration test transitive dependencies"""
    simple_repositories()
    find_links_repositories()
    find_links_repositories()
    sdist_repositories()
    transitive_ins_repositories()
