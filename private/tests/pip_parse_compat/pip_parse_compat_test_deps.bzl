"""Test dependencies for `pip_parse` compatibility tests"""

load("@bazel_tools//tools/build_defs/repo:utils.bzl", "maybe")
load("//:defs.bzl", "py_requirements_repository")

def pip_parse_compat_test_deps():
    maybe(
        py_requirements_repository,
        name = "req_compile_test_pip_parse_compat_single_plat",
        requirements_lock = Label("//private/tests/pip_parse_compat:requirements.txt"),
    )

    maybe(
        py_requirements_repository,
        name = "req_compile_test_pip_parse_compat_multi_plat",
        requirements_locks = {
            Label("//private/tests/pip_parse_compat:requirements.linux.txt"): "@platforms//os:linux",
            Label("//private/tests/pip_parse_compat:requirements.macos.txt"): "@platforms//os:macos",
            Label("//private/tests/pip_parse_compat:requirements.windows.txt"): "@platforms//os:windows",
        },
    )
