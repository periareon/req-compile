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
        http_archive,
        name = "rules_cc",
        urls = ["https://github.com/bazelbuild/rules_cc/releases/download/0.0.9/rules_cc-0.0.9.tar.gz"],
        sha256 = "2037875b9a4456dce4a79d112a8ae885bbc4aad968e6587dca6e64f3a0900cdf",
        strip_prefix = "rules_cc-0.0.9",
    )

    maybe(
        py_requirements_repository,
        name = "sdist_deps",
        # This solution file is cross-platform as of 2024/04/03
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
