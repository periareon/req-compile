"""req-compile transitive dependencies"""

load("@req_compile_deps//:defs.bzl", deps_repositories = "repositories")
load("@req_compile_sdist_compiler//:defs.bzl", sdist_deps_repositories = "repositories")
load("@rules_python//python:repositories.bzl", "py_repositories")

def req_compile_transitive_dependencies():
    """req-compile transitive dependencies"""
    py_repositories()
    deps_repositories()
    sdist_deps_repositories()
