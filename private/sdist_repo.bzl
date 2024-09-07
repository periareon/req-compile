"""Repository rules for downloading and extracting python source distribution archives"""

load(":utils.bzl", "execute", "parse_artifact_name")
load(":whl_repo.bzl", "load_sdist_data")

_BUILD_TEMPLATE = """\
package(default_visibility = ["//visibility:public"])

exports_files([
    "{whl}",
    "whl.json",
])
"""

def whl_repo_to_python_path(repository_ctx, root):
    """Convert a label into a PYTHONPATH entry.

    Args:
        repository_ctx (repository_ctx): The rule's context object.
        root (Label): The label to a file.

    Returns:
        str: A path to add to PYTHONPATH.
    """
    root_file = repository_ctx.path(root)

    return str(repository_ctx.path("{}/site-packages".format(
        root_file.dirname,
    )))

def _sdist_repository_impl(repository_ctx):
    repository_ctx.file("WORKSPACE.bazel", """workspace(name = "{}")""".format(
        repository_ctx.name,
    ))

    sdist_name = parse_artifact_name(repository_ctx.attr.urls)
    if not sdist_name:
        fail("Failed to parse sdist names for {} from {}".format(
            repository_ctx.name,
            repository_ctx.attr.urls,
        ))

    sdist_file = repository_ctx.path(sdist_name)

    sdist_result = repository_ctx.download(
        repository_ctx.attr.urls,
        output = sdist_file,
        sha256 = repository_ctx.attr.sha256,
    )

    repository_ctx.report_progress("Building wheel")

    interpreter = repository_ctx.path(repository_ctx.attr.interpreter)
    compiler = repository_ctx.path(repository_ctx.attr._compiler)

    data_file = repository_ctx.path("whl.json")

    pythonpath = [
        whl_repo_to_python_path(repository_ctx, repository_ctx.attr._dep_wheel),
        whl_repo_to_python_path(repository_ctx, repository_ctx.attr._dep_pip),
        whl_repo_to_python_path(repository_ctx, repository_ctx.attr._dep_setuptools),
    ] + [
        whl_repo_to_python_path(repository_ctx, dep)
        for dep in repository_ctx.attr.deps
    ]

    pythonpath_env = ":".join(pythonpath)

    execute(
        repository_ctx,
        args = [
            interpreter,
            "-B",  # don't write .pyc files on import; also PYTHONDONTWRITEBYTECODE=x
            "-s",  # don't add user site directory to sys.path; also PYTHONNOUSERSITE
            compiler,
            "--sdist",
            sdist_file,
            "--data_output",
            data_file,
        ],
        environment = {
            "PYTHONPATH": pythonpath_env,
            "PYTHONSAFEPATH": pythonpath_env,
        },
    )

    whl_data = load_sdist_data(repository_ctx, data_file)

    repository_ctx.file("BUILD.bazel", _BUILD_TEMPLATE.format(whl = whl_data.wheel))

    return {
        "deps": repository_ctx.attr.deps,
        "interpreter": repository_ctx.attr.interpreter,
        "name": repository_ctx.name,
        "sha256": sdist_result.sha256,
        "urls": repository_ctx.attr.urls,
        "_compiler": repository_ctx.attr._compiler,
        "_dep_pip": repository_ctx.attr._dep_pip,
        "_dep_setuptools": repository_ctx.attr._dep_setuptools,
        "_dep_wheel": repository_ctx.attr._dep_wheel,
    }

sdist_repository = repository_rule(
    doc = "A repository rule for building wheels from a python package's source distribution (sdist).",
    implementation = _sdist_repository_impl,
    attrs = {
        "deps": attr.string_list(
            doc = "A list of files representing the root of `whl_repository` for each sdist dependency.",
        ),
        "interpreter": attr.label(
            doc = "The label of a python interpreter to use for compiling source distributions (sdists).",
            allow_files = True,
            mandatory = True,
        ),
        "sha256": attr.string(
            doc = "The expected SHA-256 of the file downloaded.",
        ),
        "urls": attr.string_list(
            doc = "A list of URLs to the python wheel.",
            mandatory = True,
        ),
        "_compiler": attr.label(
            allow_files = True,
            default = Label("//private:sdist_compiler.py"),
        ),
        "_dep_pip": attr.label(
            allow_files = True,
            default = Label("@req_compile_sdist_compiler//:pip"),
        ),
        "_dep_setuptools": attr.label(
            allow_files = True,
            default = Label("@req_compile_sdist_compiler//:setuptools"),
        ),
        "_dep_wheel": attr.label(
            allow_files = True,
            default = Label("@req_compile_sdist_compiler//:wheel"),
        ),
    },
)
