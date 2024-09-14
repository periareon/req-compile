"""req-compile Bazel integration test dependencies"""

load("@bazel_tools//tools/build_defs/repo:utils.bzl", "maybe")
load("@python311//:defs.bzl", "interpreter")
load("//:defs.bzl", "py_requirements_repository")
load("//private/tests/annotations:annotations_test_deps.bzl", "req_compile_test_annotations_deps")
load("//private/tests/pip_parse_compat:pip_parse_compat_test_deps.bzl", "pip_parse_compat_test_deps")

def test_dependencies_1():
    """req-compile Bazel integration test dependencies"""

    maybe(
        py_requirements_repository,
        name = "req_compile_test_sdist",
        # Required to compile sdists
        interpreter = interpreter,
        requirements_lock = Label("//private/tests/sdist:requirements.txt"),
    )

    maybe(
        py_requirements_repository,
        name = "req_compile_test_simple",
        requirements_lock = Label("//private/tests/simple:requirements.txt"),
    )

    maybe(
        py_requirements_repository,
        name = "req_compile_test_platlib",
        requirements_locks = {
            Label("//private/tests/platlib:requirements.linux.txt"): "@platforms//os:linux",
            Label("//private/tests/platlib:requirements.macos.txt"): "@platforms//os:macos",
            Label("//private/tests/platlib:requirements.windows.txt"): "@platforms//os:windows",
        },
    )

    maybe(
        py_requirements_repository,
        name = "req_compile_test_cross_platform",
        requirements_locks = {
            Label("//private/tests/cross_platform:requirements.linux.txt"): "@platforms//os:linux",
            Label("//private/tests/cross_platform:requirements.macos.txt"): "@platforms//os:macos",
            Label("//private/tests/cross_platform:requirements.windows.txt"): "@platforms//os:windows",
        },
    )

    maybe(
        py_requirements_repository,
        name = "req_compile_test_transitive_ins",
        requirements_lock = Label("//private/tests/transitive_ins:requirements.txt"),
    )

    pip_parse_compat_test_deps()

    req_compile_test_annotations_deps()
