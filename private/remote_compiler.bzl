"""Utilities for compiling requirements on a remote machine"""

load("@rules_venv//python/venv:defs.bzl", "py_venv_binary", "py_venv_zipapp")
load("//private:compiler.bzl", "PyReqsCompilerInfo")
load(":transition.bzl", "platform_transitioned_file")

def _rlocationpath(file, workspace_name):
    """A convenience method for producing the `rlocationpath` of a file.

    Args:
        file (File): The file object to generate the path for.
        workspace_name (str): The current workspace name.

    Returns:
        str: The `rlocationpath` value.
    """
    if file.short_path.startswith("../"):
        return file.short_path[len("../"):]

    return "{}/{}".format(workspace_name, file.short_path)

def _req_compile_output_groups_impl(ctx):
    compiler_info = ctx.attr.compiler[PyReqsCompilerInfo]

    all_files = depset(transitive = [
        compiler_info.requirements_in[DefaultInfo].files,
        compiler_info.requirements_in[DefaultInfo].default_runfiles.files,
        compiler_info.solution[DefaultInfo].files,
        compiler_info.solution[DefaultInfo].default_runfiles.files,
    ])

    args_file = ctx.attr.compiler[OutputGroupInfo].req_compile_args_file.to_list()[0]
    solution = compiler_info.solution[DefaultInfo].files.to_list()[0]

    return [
        DefaultInfo(
            files = all_files,
        ),
        platform_common.TemplateVariableInfo({
            "PY_REQ_COMPILER_ARGS_FILE": _rlocationpath(args_file, ctx.workspace_name),
            "PY_REQ_COMPILER_SOLUTION_FILE": _rlocationpath(solution, ctx.workspace_name),
        }),
        platform_common.ToolchainInfo(),
    ]

_req_compile_output_groups = rule(
    doc = "A rule for extracting variables attributes from the `py_req_compiler` target.",
    implementation = _req_compile_output_groups_impl,
    attrs = {
        "compiler": attr.label(
            doc = "The `py_req_compiler` target.",
            mandatory = True,
            providers = [PyReqsCompilerInfo],
        ),
    },
)

def py_reqs_remote_compiler(name, compiler, platform = None, **kwargs):
    """A tool for compiling python requirements on a remote machine.

    This rule wraps a `py_req_compiler` target behind a transition and
    when a ssh user and host are provided, this target can deploy the
    compiler to the remote system and perform compilation.

    Args:
        name (str): The name of the new target.
        compiler (Label): The `py_req_compiler` target.
        platform (Label): The platform label to transition to.
        **kwargs (dict): Additional keyword arguments.
    """
    tags = kwargs.pop("tags", [])
    visibility = kwargs.pop("tags", [])
    silence_kwargs = dict(kwargs.items())
    silence_kwargs["tags"] = depset(tags + ["manual"]).to_list()
    silence_kwargs["visibility"] = ["//visibility:private"]

    _req_compile_output_groups(
        name = name + "_output_groups",
        compiler = compiler,
        **silence_kwargs
    )

    py_venv_binary(
        name = name + "_bin",
        srcs = [Label("//private:remote_compiler.py")],
        main = Label("//private:remote_compiler.py"),
        data = [
            compiler,
            name + "_output_groups",
        ],
        toolchains = [
            name + "_output_groups",
        ],
        env = {
            "COMPILER": "$(rlocationpath {})".format(compiler),
            "PY_REQ_COMPILER_ARGS_FILE": "$(PY_REQ_COMPILER_ARGS_FILE)",
            "PY_REQ_COMPILER_SOLUTION_FILE": "$(PY_REQ_COMPILER_SOLUTION_FILE)",
        },
        deps = ["@rules_python//python/runfiles"],
    )

    # Create a zipapp for the desired platform.
    py_venv_zipapp(
        name = name + ".pyz",
        binary = name + "_bin",
        inherit_env = True,
        **silence_kwargs
    )

    zipapp = name + ".pyz"
    if platform:
        platform_transitioned_file(
            name = name + "_transition",
            platform = platform,
            target = name + ".pyz",
            **silence_kwargs
        )
        zipapp = name + "_transition"

    # Define a binary that will run the tool.
    py_venv_binary(
        name = name,
        srcs = [Label("//private:remote_orchestrator.py")],
        main = Label("//private:remote_orchestrator.py"),
        deps = [Label("@rules_venv//python/runfiles")],
        tags = tags,
        data = [zipapp],
        env = {
            "COMPILER": "$(rlocationpath {})".format(zipapp),
        },
        visibility = visibility,
        **kwargs
    )
