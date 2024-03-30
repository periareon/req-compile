"""req-compile Bazel integration test transitive dependencies"""

load("@bazel_tools//tools/build_defs/repo:utils.bzl", "maybe")
load("@req_compile_test_sdist//:defs.bzl", sdist_repositories = "repositories")
load("@req_compile_test_simple//:defs.bzl", simple_repositories = "repositories")
load("@req_compile_test_transitive_ins//:defs.bzl", transitive_ins_repositories = "repositories")
load("//:defs.bzl", "py_requirements_repository")

def test_dependencies_2():
    """req-compile Bazel integration test transitive dependencies"""
    simple_repositories()
    sdist_repositories()
    transitive_ins_repositories()

    maybe(
        py_requirements_repository,
        name = "req_compile_test_find_links",
        requirements_lock = Label("@req_compile_find_links_test//:requirements.txt"),
    )
