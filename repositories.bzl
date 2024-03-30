"""req-compile dependencies"""

load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")
load("@bazel_tools//tools/build_defs/repo:utils.bzl", "maybe")
load("//private:reqs_repo.bzl", "py_requirements_repository")

def req_compile_dependencies():
    """req-compile dependencies"""
    maybe(
        http_archive,
        name = "rules_python",
        sha256 = "c68bdc4fbec25de5b5493b8819cfc877c4ea299c0dcb15c244c5a00208cde311",
        strip_prefix = "rules_python-0.31.0",
        url = "https://github.com/bazelbuild/rules_python/releases/download/0.31.0/rules_python-0.31.0.tar.gz",
    )

    maybe(
        py_requirements_repository,
        name = "req_compile_sdist_compiler",
        requirements_lock = Label("//private:sdist_requirements.txt"),
    )

    maybe(
        py_requirements_repository,
        name = "req_compile_deps",
        requirements_locks = {
            Label("//3rdparty:requirements.linux.311.txt"): "@platforms//os:linux",
            Label("//3rdparty:requirements.macos.311.txt"): "@platforms//os:macos",
            Label("//3rdparty:requirements.windows.311.txt"): "@platforms//os:windows",
        },
    )
