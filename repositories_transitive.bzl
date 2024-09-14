"""req-compile transitive dependencies"""

load("@req_compile_deps//:defs.bzl", deps_repositories = "repositories")
load("@rules_python//python:repositories.bzl", "py_repositories")
load("@sdist_deps//:defs.bzl", sdist_deps_repositories = "repositories")

def req_compile_transitive_dependencies():
    """req-compile transitive dependencies"""
    py_repositories()
    deps_repositories()
    sdist_deps_repositories()
