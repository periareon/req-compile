"""Rules for compiling requirements files"""

_PYTHON_TOOLCHAIN_TYPE = "@rules_python//python:toolchain_type"

PyReqsCompilerInfo = provider(
    doc = "Information about a python requirements provider",
    fields = {
        "args": "List[str]: A list of arguments core to the compiler.",
        "requirements_in": "Target: The `requirements_in` target which provides requirement files.",
        "solutions": "List[Target]: The solution files which represent the compiled results from `requirements_in`, one per platform.",
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

    # `rules_venv` entrypoints are `.bat` scripts on Windows and `.sh` scripts elsewhere.
    is_windows = executable.basename.endswith(".bat")
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

    return link, runfiles

def _solutions(ctx):
    """Collect the solution files of a `py_reqs_compiler` target and their platforms.

    Args:
        ctx (ctx): The rule's context object

    Returns:
        List[struct]: One struct per solution with the fields `file` (File), `target`
            (Target) and `platform` (Optional[str]).
    """
    if ctx.attr.requirements_txt and ctx.attr.requirements_txts:
        fail("`requirements_txt` and `requirements_txts` are mutually exclusive. Please update {}".format(
            ctx.label,
        ))

    if ctx.attr.requirements_txts:
        if ctx.attr.platform:
            fail("`platform` only applies to `requirements_txt`, `requirements_txts` maps each solution to its platform. Please update {}".format(
                ctx.label,
            ))
        solutions = []
        for target, platform in ctx.attr.requirements_txts.items():
            files = target.files.to_list()
            if len(files) != 1:
                fail("`requirements_txts` entries must each be a single file, {} provides {}. Please update {}".format(
                    target.label,
                    len(files),
                    ctx.label,
                ))
            if not platform:
                fail("`requirements_txts` must map {} to the platform it is compiled for. Please update {}".format(
                    target.label,
                    ctx.label,
                ))
            solutions.append(struct(file = files[0], target = target, platform = platform))
        return solutions

    if not ctx.attr.requirements_txt:
        fail("One of `requirements_txt` or `requirements_txts` is required. Please update {}".format(
            ctx.label,
        ))

    return [struct(
        file = ctx.file.requirements_txt,
        target = ctx.attr.requirements_txt,
        platform = ctx.attr.platform or None,
    )]

def _py_reqs_compiler_impl(ctx):
    compiler, runfiles = _symlink_py_executable(ctx, ctx.attr._compiler[0])

    solutions = _solutions(ctx)

    custom_compile_command = ctx.expand_location(
        ctx.attr.custom_compile_command.replace("{label}", str(ctx.label)),
        [ctx.attr.requirements_in] + [solution.target for solution in solutions],
    )

    args = [
        "--requirements_file",
        _rlocationpath(ctx.file.requirements_in, ctx.workspace_name),
    ]
    for solution in solutions:
        args.extend(["--solution", _rlocationpath(solution.file, ctx.workspace_name)])
    args.extend([
        "--custom_compile_command",
        json.encode(custom_compile_command),
    ])

    if ctx.attr.allow_sdists:
        args.append("--allow_sdists")

    for solution in solutions:
        if solution.platform:
            args.extend(["--platform", solution.platform])

    python_version = ctx.attr.python_version
    if not python_version:
        # Default to the exact version of the toolchain so that the solution, and the
        # header recorded in it, do not depend on the machine running the compiler.
        toolchain = ctx.toolchains[_PYTHON_TOOLCHAIN_TYPE]
        runtime = getattr(toolchain, "py3_runtime", None) if toolchain else None
        info = getattr(runtime, "interpreter_version_info", None) if runtime else None
        if info:
            python_version = "{}.{}.{}".format(info.major, info.minor, info.micro)

    if python_version:
        args.extend(["--python_version", python_version])

    outputs = []
    for solution in solutions:
        outputs.extend(["--output", solution.file.short_path])

    args_file = ctx.actions.declare_file("{}.args.txt".format(ctx.label.name))
    ctx.actions.write(
        output = args_file,
        content = "\n".join(args + outputs),
    )

    runfiles = runfiles.merge_all([
        ctx.runfiles(files = [
            args_file,
            ctx.file.requirements_in,
        ] + [solution.file for solution in solutions]),
        ctx.attr.requirements_in[DefaultInfo].default_runfiles,
    ] + [solution.target[DefaultInfo].default_runfiles for solution in solutions])

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
            solutions = [solution.target for solution in solutions],
        ),
        OutputGroupInfo(
            req_compile_args_file = depset([args_file]),
            req_compile_solution_file = depset([solution.file for solution in solutions]),
        ),
    ]

py_reqs_compiler = rule(
    doc = """\
A Bazel rule for compiling python requirements.


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
a clean resolution (fetching latest for all requirements) the `--upgrade` flag can be used. A solution compiled for
another platform or Python version, as recorded in its header, is not recycled: changing the `platform` or
`python_version` of the rule resolves the requirements again.

```bash
bazel run //:requirements.update -- --upgrade
```

By default a solution is compiled for the platform and Python version running the compiler. The `platform` and
`python_version` attributes compile a solution for a different environment, so solutions for every platform a
project supports can be produced and tested from any machine. To support several platforms, map a solution file
to each platform with `requirements_txts`. One target then compiles every solution, and the solutions always use
the same version of each package: a package keeps the version the first platform resolves it to and a version
that another platform cannot use, e.g. because no wheel is published for it, is dropped for all of them. When no
version of a package works on every platform the compilation fails and names the platforms that disagree, so
the package can be constrained in the requirements. A `py_reqs_solution_test` of the target checks every
solution, including that they agree.

```python
load("@rules_req_compile//:defs.bzl", "py_reqs_compiler", "py_reqs_solution_test")

py_reqs_compiler(
    name = "requirements.update",
    requirements_in = ":requirements",
    requirements_txts = {
        "requirements.linux.txt": "manylinux_2_28_x86_64",
        "requirements.macos.txt": "macosx_11_0_arm64",
        "requirements.windows.txt": "win_amd64",
    },
)

py_reqs_solution_test(
    name = "requirements_test",
    compiler = ":requirements.update",
)
```

The versions pinned by any of the solutions are recycled for all of them, so a platform added to
`requirements_txts` starts from the versions the others use. Solutions for different Python versions frequently
cannot share versions, so define one `py_reqs_compiler` per Python version.

Wheels are selected and environment markers are evaluated as they would be when installing on the target.
Source distributions (sdists) have their metadata extracted on the machine running the compiler, so solutions
for other platforms should avoid them, which is the default (`allow_sdists = False`).
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
        "platform": attr.string(
            doc = (
                "The platform to compile the solution for as a wheel platform tag, as accepted by " +
                "`pip --platform`, e.g. `manylinux_2_28_x86_64`, `manylinux2014_aarch64`, `macosx_11_0_arm64` " +
                "or `win_amd64`. A manylinux tag accepts wheels for that glibc or older, a macosx tag wheels " +
                "for that release or older. When unset, the solution is compiled for the platform running " +
                "the compiler. Only applies to `requirements_txt`, `requirements_txts` names the platform " +
                "of each solution."
            ),
        ),
        "python_version": attr.string(
            doc = (
                "The Python version to compile the solution for, e.g. `3.11.4`. When unset, the exact " +
                "version of the resolved Python toolchain is used, which keeps the solution independent " +
                "of the machine running the compiler. A version without a patch number, e.g. `3.9`, is " +
                "compiled as `3.9.0`."
            ),
        ),
        "requirements_in": attr.label(
            doc = "The input requirements file",
            allow_single_file = True,
            mandatory = True,
        ),
        "requirements_txt": attr.label(
            doc = "The solution file. Mutually exclusive with `requirements_txts`.",
            allow_single_file = True,
        ),
        "requirements_txts": attr.label_keyed_string_dict(
            doc = (
                "Solution files mapped to the wheel platform tag each is compiled for, see `platform`. " +
                "The solutions are compiled together and use the same version of every package. " +
                "Mutually exclusive with `requirements_txt` and `platform`."
            ),
            allow_files = True,
        ),
        "_compiler": attr.label(
            cfg = _compilation_mode_opt_transition,
            executable = True,
            default = Label("//req_compile/private:compiler_bin"),
        ),
        "_copier": attr.label(
            cfg = "exec",
            executable = True,
            default = Label("//req_compile/private:copier"),
        ),
    },
    executable = True,
    toolchains = [config_common.toolchain_type(_PYTHON_TOOLCHAIN_TYPE, mandatory = False)],
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
                ] + [
                    solution[DefaultInfo].files
                    for solution in compile_info.solutions
                ]),
            ),
            compile_info.requirements_in[DefaultInfo].default_runfiles,
        ] + [
            solution[DefaultInfo].default_runfiles
            for solution in compile_info.solutions
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
            default = Label("//req_compile/private:copier"),
        ),
        "_tester": attr.label(
            cfg = "target",
            executable = True,
            default = Label("//req_compile/private:solution_tester"),
        ),
    },
    test = True,
)
