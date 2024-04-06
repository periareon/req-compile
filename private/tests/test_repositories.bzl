"""req-compile Bazel integration test dependencies"""

load("@bazel_tools//tools/build_defs/repo:utils.bzl", "maybe")
load("@python_3_11//:defs.bzl", "interpreter")
load("//:defs.bzl", "py_requirements_repository")

def test_dependencies():
    """req-compile Bazel integration test dependencies"""

    maybe(
        py_requirements_repository,
        name = "req_compile_test_find_links",
        requirements_lock = Label("//private/tests/find_links:requirements.txt"),
    )

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
        name = "req_compile_test_transitive_ins",
        requirements_lock = Label("//private/tests/transitive_ins:requirements.txt"),
    )
