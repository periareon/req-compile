"""Rules for compiling requirements files"""

PyReqsCompilerInfo = provider(
    doc = "Information about a python requirements provider",
    fields = {
        "args": "List[str]: A list of arguments core to the compiler.",
        "requirements_in": "Target: The `requirements_in` target which provides requirement files.",
        "solution": "Target: The solution file which represents the compiled result from `requirements_in`.",
    },
)

def _compilation_mode_opt_transition_impl(settings, _attr):
    output = dict(settings)
    output["//command_line_option:compilation_mode"] = "opt"
    return output

_compilation_mode_opt_transition = transition(
    implementation = _compilation_mode_opt_transition_impl,
    outputs = ["//command_line_option:compilation_mode"],
    inputs = [],
)

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

def _symlink_py_executable(ctx, target):
    """Create an executable symlink to a `py_bianry` entrypoint.

    This function exists because executable rules __must__ produce the executable it represents.

    Args:
        ctx (ctx): The rule's context object
        target (Target): The `py_binary` target to create symlinks for.

    Returns:
        Tuple[File, Runfiles]: The executable output and associated runfiles.
    """
    executable = target[DefaultInfo].files_to_run.executable
    is_windows = executable.basename.endswith(".exe")
    link = ctx.actions.declare_file("{}.{}".format(ctx.label.name, executable.basename))

    # Unfortunately on Windows, the use of `ctx.actions.symlink` leads to build failures
    # when outputs are downloaded using builds-without-the-bytes. To avoid this, the file
    # is copied instead of being symlinked. For more details see:
    # https://github.com/bazelbuild/bazel/issues/21747
    if is_windows:
        args = ctx.actions.args()
        args.add(executable)
        args.add(link)
        ctx.actions.run(
            executable = ctx.executable._copier,
            mnemonic = "CopyFile",
            arguments = [args],
            inputs = [executable],
            outputs = [link],
        )
    else:
        ctx.actions.symlink(
            output = link,
            target_file = executable,
            is_executable = True,
        )

    runfiles = ctx.runfiles()
    runfiles = runfiles.merge(target[DefaultInfo].default_runfiles)

    # Windows will require the zipapp provided by py_binary targets
    if is_windows and hasattr(target[OutputGroupInfo], "python_zip_file"):
        _, _, zipapp_name = link.path.rpartition("/")
        zipapp = ctx.actions.declare_file(zipapp_name.replace(".exe", ".zip"), sibling = link)

        # This output group is expected to only contain 1 file
        python_zip_file = target[OutputGroupInfo].python_zip_file.to_list()[0]
        if is_windows:
            args = ctx.actions.args()
            args.add(python_zip_file)
            args.add(zipapp)
            ctx.actions.run(
                executable = ctx.executable._copier,
                mnemonic = "CopyFile",
                arguments = [args],
                inputs = [python_zip_file],
                outputs = [zipapp],
            )
        else:
            ctx.actions.symlink(
                output = zipapp,
                target_file = python_zip_file,
                is_executable = True,
            )
        runfiles = runfiles.merge(ctx.runfiles(files = [zipapp]))

    return link, runfiles

def _py_reqs_compiler_impl(ctx):
    compiler, runfiles = _symlink_py_executable(ctx, ctx.attr._compiler[0])

    custom_compile_command = ctx.expand_location(ctx.attr.custom_compile_command.replace("{label}", str(ctx.label)), [
        ctx.attr.requirements_in,
        ctx.attr.requirements_txt,
    ])

    args = [
        "--requirements_file",
        _rlocationpath(ctx.file.requirements_in, ctx.workspace_name),
        "--solution",
        _rlocationpath(ctx.file.requirements_txt, ctx.workspace_name),
        "--custom_compile_command",
        json.encode(custom_compile_command),
    ]

    if ctx.attr.allow_sdists:
        args.append("--allow_sdists")

    args_file = ctx.actions.declare_file("{}.args.txt".format(ctx.label.name))
    ctx.actions.write(
        output = args_file,
        content = "\n".join(args + [
            "--output",
            ctx.file.requirements_txt.short_path,
        ]),
    )

    runfiles = runfiles.merge_all([
        ctx.runfiles(files = [
            args_file,
            ctx.file.requirements_in,
            ctx.file.requirements_txt,
        ]),
        ctx.attr.requirements_in[DefaultInfo].default_runfiles,
    ])

    return [
        RunEnvironmentInfo(
            environment = {
                "PY_REQ_COMPILER_ARGS_FILE": _rlocationpath(args_file, ctx.workspace_name),
            },
        ),
        DefaultInfo(
            executable = compiler,
            files = depset([compiler]),
            runfiles = runfiles,
        ),
        PyReqsCompilerInfo(
            args = args,
            requirements_in = ctx.attr.requirements_in,
            solution = ctx.attr.requirements_txt,
        ),
        OutputGroupInfo(
            req_compile_args_file = depset([args_file]),
            req_compile_solution_file = depset([ctx.file.requirements_txt]),
        ),
    ]

py_reqs_compiler = rule(
    doc = """\
A Bazel rule for compiling python requirements for the current platform.


```python
load("@rules_req_compile//:defs.bzl", "py_reqs_compiler", "py_reqs_solution_test")

filegroup(
    name = "requriements",
    srcs = ["requirements.in"],
    data = [
        # Any transitive files included via `-r` should be added here.
    ],
)

py_reqs_compiler(
    name = "requirements.update",
    requirements_in = ":requirements",
    requirements_txt = "requirements.txt",
)

```

Updating requirements can be performed by running the new target.

```bash
bazel run //:requirements.update
```

By default the rule will try to recycle pins already existing in the solution file (`requirements.txt`). To perform
a clean resolution (fetching latest for all requirements) the `--upgrade` flag can be used.

```bash
bazel run //:requirements.update -- --upgrade
```
""",
    implementation = _py_reqs_compiler_impl,
    attrs = {
        "allow_sdists": attr.bool(
            doc = "Whether or not the solution file is allowed to contain sdist packages.",
            default = False,
        ),
        "custom_compile_command": attr.string(
            doc = (
                "The command to display in the header of the generated lock file (`requirements_txt`). " +
                "Any references to `{label}` will be replaced with the label of this target."
            ),
            default = "bazel run \"{label}\"",
        ),
        "requirements_in": attr.label(
            doc = "The input requirements file",
            allow_single_file = True,
            mandatory = True,
        ),
        "requirements_txt": attr.label(
            doc = "The solution file.",
            allow_single_file = True,
            mandatory = True,
        ),
        "_compiler": attr.label(
            cfg = _compilation_mode_opt_transition,
            executable = True,
            default = Label("//private:compiler"),
        ),
        "_copier": attr.label(
            cfg = "exec",
            executable = True,
            default = Label("//private:copier"),
        ),
    },
    executable = True,
)

def _py_reqs_solution_test_impl(ctx):
    tester, runfiles = _symlink_py_executable(ctx, ctx.attr._tester)

    if ctx.attr.compiler and ctx.attr.requirements_in:
        fail("`compiler` and (`requirements_in` + `requirements_txt`) are mutually exclusive. Please update {}".format(
            ctx.label,
        ))

    args = ctx.actions.args()
    args.set_param_file_format("multiline")
    args_file = ctx.actions.declare_file("{}.args.txt".format(ctx.label.name))
    runfiles = runfiles.merge(ctx.runfiles(files = [args_file]))

    if ctx.attr.compiler:
        compile_info = ctx.attr.compiler[PyReqsCompilerInfo]
        args.add_all(compile_info.args)

        runfiles = runfiles.merge_all([
            ctx.runfiles(
                transitive_files = depset(transitive = [
                    compile_info.requirements_in[DefaultInfo].files,
                    compile_info.solution[DefaultInfo].files,
                ]),
            ),
            compile_info.requirements_in[DefaultInfo].default_runfiles,
            compile_info.solution[DefaultInfo].default_runfiles,
        ])
    elif ctx.attr.requirements_in or ctx.attr.requirements_txt:
        if not ctx.attr.requirements_in and not ctx.attr.requirements_txt:
            fail("Both `requirements_in` and `requirements_txt` are required when either are set. Please update {}".format(
                ctx.label,
            ))
        if not ctx.attr.custom_compile_command:
            fail("`custom_compile_command` is required with `requirements_in` and `requirements_txt`. Please update {}".format(
                ctx.label,
            ))

        custom_compile_command = ctx.expand_location(ctx.attr.custom_compile_command, [
            ctx.attr.requirements_in,
            ctx.attr.requirements_txt,
        ])

        args.add("--requirements_file", _rlocationpath(ctx.file.requirements_in, ctx.workspace_name))
        args.add("--solution", _rlocationpath(ctx.file.requirements_txt, ctx.workspace_name))
        args.add("--custom_compile_command", json.encode(custom_compile_command))

        runfiles = runfiles.merge_all([
            ctx.runfiles(
                transitive_files = depset(transitive = [
                    ctx.attr.requirements_in[DefaultInfo].files,
                    ctx.attr.requirements_txt[DefaultInfo].files,
                ]),
            ),
            ctx.attr.requirements_in[DefaultInfo].default_runfiles,
            ctx.attr.requirements_txt[DefaultInfo].default_runfiles,
        ])
    else:
        fail("Either `compiler` or (`requirements_in` + `requirements_txt`) are required. Please update {}".format(
            ctx.label,
        ))

    args.add("--no_index")

    ctx.actions.write(
        output = args_file,
        content = args,
    )

    return [
        RunEnvironmentInfo(
            environment = {
                "PY_REQ_COMPILER_ARGS_FILE": _rlocationpath(args_file, ctx.workspace_name),
            },
        ),
        DefaultInfo(
            executable = tester,
            files = depset([tester]),
            runfiles = runfiles,
        ),
    ]

py_reqs_solution_test = rule(
    doc = """\
A Bazel test rule for ensuring the solution file for a `py_reqs_compiler` target satisifes the given requirements (`requirements_in`).

```python
load("@rules_req_compile//:defs.bzl", "py_reqs_compiler", "py_reqs_solution_test")

py_reqs_compiler(
    name = "requirements.update",
    requirements_in = "requirements.in",
    requirements_txt = "requirements.txt",
)

py_reqs_solution_test(
    name = "requirements_test",
    requirements_in = "requirements.in",
    requirements_txt = "requirements.txt",
)
```

Alternatively, a test can be defined in isolation using just the requirements files:

```python
load("@rules_req_compile//:defs.bzl", "py_reqs_solution_test")

py_reqs_solution_test(
    name = "requirements_test",
    custom_compile_command = "python3 -m req_compile --multiline --hashes --urls --solution requirements.txt requirements.in",
    requirements_in = "requirements.in",
    requirements_txt = "requirements.txt",
)
```
""",
    implementation = _py_reqs_solution_test_impl,
    attrs = {
        "compiler": attr.label(
            doc = (
                "The `py_reqs_compiler` target to test. This attribute is " +
                "mutally exclusive with `requirements_in` and `requirements_txt` " +
                "and does not do any string formatting like `py_reqs_compiler` does."
            ),
            providers = [PyReqsCompilerInfo],
        ),
        "custom_compile_command": attr.string(
            doc = (
                "The command to display in the header of the generated lock file (`requirements_txt`). " +
                "This attribute is required with `requirements_in` and `requirements_txt`."
            ),
        ),
        "requirements_in": attr.label(
            doc = "The input requirements file. This attribute is mutually exclusive with `compiler`.",
            allow_single_file = True,
        ),
        "requirements_txt": attr.label(
            doc = "The solution file. This attribute is mutually exclusive with `compiler`.",
            allow_single_file = True,
        ),
        "_copier": attr.label(
            cfg = "exec",
            executable = True,
            default = Label("//private:copier"),
        ),
        "_tester": attr.label(
            cfg = "target",
            executable = True,
            default = Label("//private:solution_tester"),
        ),
    },
    test = True,
)
