"""Utilities for compiling requirements on a remote machine"""

load("@rules_venv//python/venv:defs.bzl", "py_venv_binary", "py_venv_zipapp")
load("//private:compiler.bzl", "PyReqsCompilerInfo")
load(":transition.bzl", "platform_transitioned_file")

def _req_compile_output_file_impl(ctx):
    outputs = getattr(ctx.attr.compiler[OutputGroupInfo], ctx.attr.output_group)
    if not outputs:
        fail(
            "Could not find output group '{}' in '{}'".format(
                ctx.attr.output_group,
                ctx.attr.compiler.label,
            ),
        )

    output_file = outputs.to_list()[0]
    link = ctx.actions.declare_file(
        "{}.{}".format(ctx.label.name, output_file.extension).rstrip("."),
    )
    ctx.actions.symlink(
        output = link,
        target_file = output_file,
    )

    return [DefaultInfo(files = depset([link]))]

_req_compile_output_file = rule(
    doc = "A rule for accessing a single file from a `py_req_compiler` output group.",
    implementation = _req_compile_output_file_impl,
    attrs = {
        "compiler": attr.label(
            doc = "The `py_req_compiler` target.",
            mandatory = True,
            providers = [PyReqsCompilerInfo],
        ),
        "output_group": attr.string(
            doc = "The `OutputGroupInfo` field to access.",
            mandatory = True,
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

    _req_compile_output_file(
        name = name + "_args_file",
        compiler = compiler,
        output_group = "req_compile_args_file",
        **silence_kwargs
    )
    _req_compile_output_file(
        name = name + "_solution_file",
        compiler = compiler,
        output_group = "req_compile_solution_file",
        **silence_kwargs
    )

    py_venv_binary(
        name = name + "_bin",
        srcs = [Label("//private:remote_compiler.py")],
        main = Label("//private:remote_compiler.py"),
        data = [
            compiler,
            name + "_args_file",
            name + "_solution_file",
        ],
        env = {
            "COMPILER": "$(rlocationpath {})".format(compiler),
            "PY_REQ_COMPILER_ARGS_FILE": "$(rlocationpath {})".format(name + "_args_file"),
            "PY_REQ_COMPILER_SOLUTION_FILE": "$(rlocationpath {})".format(name + "_solution_file"),
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
