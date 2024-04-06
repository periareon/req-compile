"""req-compile Bazel integration test dependencies"""

load("@bazel_tools//tools/build_defs/repo:utils.bzl", "maybe")
load("@python_3_11//:defs.bzl", "interpreter")
load("//:defs.bzl", "py_requirements_repository")
load("//private/tests/find_links:find_links_test_repo.bzl", "find_links_test_repository")

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
        name = "req_compile_test_transitive_ins",
        requirements_lock = Label("//private/tests/transitive_ins:requirements.txt"),
    )

    maybe(
        find_links_test_repository,
        name = "req_compile_find_links_test",
        pyspark_wheel_data = Label("@req_compile_test_sdist__pyspark__sdist//:whl.json"),
        build_file = Label("//private/tests/find_links:BUILD.find_links.bazel"),
        # Needs to match `--find-links` in `//private/tests/find_links:requirements.in`
        wheeldir = "wheeldir",
        requirements_in = Label("//private/tests/find_links:requirements.in"),
        requirements_txt = Label("//private/tests/find_links:requirements.txt"),
    )
