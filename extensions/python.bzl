"""Python requirements module extension."""

load(
    "//:defs.bzl",
    package_annotation = "py_package_annotation",
)
load(
    "//private:reqs_repo.bzl",
    "BUILD_FILE_TEMPLATE",
    "RULES_PYTHON_COMPAT",
    "generate_interface_bzl_content",
    "process_lockfile",
    "write_defs_file",
)
load("//private:sdist_repo.bzl", "sdist_repository")
load("//private:whl_repo.bzl", "whl_repository")

def _is_wheel(data):
    if "url" in data and data["url"]:
        if ".whl" in data["url"]:
            return True
        return False

    if "whl" in data and data["whl"]:
        return True

    return False

def _reqs_hub_impl(repository_ctx):
    repository_ctx.file(
        "BUILD.bazel",
        BUILD_FILE_TEMPLATE.format(
            packages = json.encode_indent(
                sorted(depset(repository_ctx.attr.packages).to_list()),
            ),
        ),
    )
    for defs_id in repository_ctx.attr.defs:
        defs_file = repository_ctx.path("defs_{}.bzl".format(defs_id))
        write_defs_file(
            repository_ctx,
            repository_ctx.attr.packages,
            defs_file,
            defs_id,
            name = repository_ctx.attr.hub_name,
        )

    repository_ctx.file(
        "requirements.bzl",
        RULES_PYTHON_COMPAT.format(
            repository_name = repository_ctx.name,
        ),
    )
    repository_ctx.file(
        "defs.bzl",
        generate_interface_bzl_content(repository_ctx.attr.defs, repository_ctx.name),
    )

reqs_hub = repository_rule(
    implementation = _reqs_hub_impl,
    attrs = {
        "hub_name": attr.string(),
        "defs": attr.string_dict(),
        "packages": attr.string_list(),
        "interpreter": attr.label(),
    },
)

def _requirements_impl(ctx):
    extension_namespace = "@@" + ctx.path(".").basename
    extension_sep = "~"

    # Support --incompatible_use_plus_in_repo_names
    if extension_namespace.startswith("@@+"):
        extension_sep = "+"

    annotations = {}
    for mod in ctx.modules:
        for annotation in mod.tags.package_annotation:
            annotations[annotation.package] = package_annotation(
                additive_build_file = annotation.additive_build_file,
                additive_build_file_content = annotation.additive_build_file_content,
                copy_srcs = annotation.copy_srcs,
                copy_files = annotation.copy_files,
                copy_executables = annotation.copy_executables,
                data = annotation.data,
                data_exclude_glob = annotation.data_exclude_glob,
                srcs_exclude_glob = annotation.srcs_exclude_glob,
                deps = annotation.deps,
                deps_excludes = annotation.deps_excludes,
                patches = annotation.patches,
            )

    for mod in ctx.modules:
        for parse in mod.tags.parse:
            all_packages = []
            defs = {}

            requirements_locks = {}
            if parse.requirements_locks:
                requirements_locks = parse.requirements_locks

            if parse.requirements_lock:
                requirements_locks = {parse.requirements_lock: "//conditions:default"}

            for lock, constraint in requirements_locks.items():
                constraint = str(Label(constraint))
                lockfile = ctx.path(lock)

                defs_id, _, _ = lockfile.basename.rpartition(".")
                defs_id = (
                    defs_id.replace("requirements", "")
                        .replace(".", "_")
                        .replace("-", "_")
                        .strip(" _.")
                )
                if not defs_id:
                    defs_id = "any"
                defs.update({defs_id: constraint})

                packages = process_lockfile(
                    repository_ctx = ctx,
                    requirements_lock = lock,
                    constraint = constraint,
                    name = parse.name,
                    annotations = annotations,
                )
                all_packages.extend(packages.keys())

                for repo_name, data in packages.items():
                    name = parse.name + "_" + defs_id + "__" + repo_name
                    if _is_wheel(data):
                        whl_repository(
                            name = name,
                            annotations = json.encode(data["annotations"]),
                            constraint = data["constraint"],
                            deps = data["deps"],
                            package = name,
                            reqs_repository_name = parse.name + "_" + defs_id,
                            sha256 = data["sha256"],
                            urls = [data["url"]] if data.get("url", None) else None,
                            version = data["version"],
                            whl = data["whl"],
                        )
                    else:
                        interpreter = None
                        if ctx.os.name == "mac os x":
                            if ctx.os.arch == "amd64":
                                interpreter = parse.interpreter_macos_intel
                            else:
                                interpreter = parse.interpreter_macos_aarch64
                        elif ctx.os.name == "linux":
                            interpreter = parse.interpreter_linux
                        elif ctx.os.name.startswith("windows"):
                            interpreter = parse.interpreter_windows
                        else:
                            fail("Unsupported platform {}".format(ctx.os.name))

                        if not interpreter:
                            fail(
                                "A sdist (" +
                                name +
                                ") was found for the repository '{repository_name}' " +
                                "but no interpreter was provided. One is required for processing sdists.",
                            )
                        sdist_repository(
                            name = "{}_{}__sdist".format(name, defs_id),
                            sha256 = data["sha256"],
                            urls = [data["url"]],
                            interpreter = interpreter,
                        )
                        whl_repository(
                            name = name,
                            annotations = json.encode(data["annotations"]),
                            constraint = data["constraint"],
                            deps = data["deps"],
                            package = name,
                            reqs_repository_name = parse.name,
                            whl_data = Label(
                                "{}{}{}_{}__sdist//:whl.json".format(
                                    extension_namespace,
                                    extension_sep,
                                    name,
                                    defs_id,
                                ),
                            ),
                            version = data["version"],
                        )

            reqs_hub(
                name = parse.name,
                hub_name = parse.name,
                defs = defs,
                packages = all_packages,
            )

_annotation = tag_class(
    doc = """\
An annotation representing a annotation editing a Python package.

See [@rules_python//python:pip.bzl%package_annotation](https://github.com/bazelbuild/rules_python/blob/main/docs/pip_repository.md#package_annotation)
for more information.
""",
    attrs = {
        "package": attr.string(),
        "additive_build_file": attr.label(),
        "additive_build_file_content": attr.string(),
        "copy_srcs": attr.string_dict(),
        "copy_files": attr.string_dict(),
        "copy_executables": attr.string_dict(),
        "data": attr.string_list(),
        "data_exclude_glob": attr.string_list(),
        "srcs_exclude_glob": attr.string_list(),
        "deps": attr.string_list(),
        "deps_excludes": attr.string_list(),
        "patches": attr.label_list(),
    },
)

_parse = tag_class(
    doc = """"\
Parse a lock file into a hub repo.

A hub repo is a single repository that can be pulled into another
module via `use_repo` and contains all of the Python wheel repos
specified by the requirements files.

Aliases are added at the top-level package of the hub repo to each
package it contains, using a normalized name of the Python project.

```python
requirements = use_extension("@rules_req_compile//extensions:python.bzl", "requirements")
requirements.parse(
    name = "pip_deps",
    requirements_locks = {
        "//3rdparty:requirements.linux.311.txt": "@platforms//os:linux",
        "//3rdparty:requirements.macos.311.txt": "@platforms//os:macos",
        "//3rdparty:requirements.windows.311.txt": "@platforms//os:windows",
    },
)
use_repo(requirements, "pip_deps")
```

This example was a multi-platform set of solutions, pulled into a single
hub repository named "pip_deps".
""",
    attrs = {
        "name": attr.string(
            doc = "Name of the hub repository to create.",
            mandatory = True,
        ),
        "interpreter_linux": attr.label(
            doc = "Optional Linux amd64 Python interpreter binary to use for sdists.",
        ),
        "interpreter_macos_intel": attr.label(
            doc = "Optional MacOS intel Python interpreter binary to use for sdists.",
        ),
        "interpreter_macos_aarch64": attr.label(
            doc = "Optional MacOS ARM Python interpreter binary to use for sdists.",
        ),
        "interpreter_windows": attr.label(
            doc = "Optional Windows x64 Python interpreter binary to use for sdists.",
        ),
        "requirements_lock": attr.label(
            doc = "A single lockfile for a single platform solution.",
        ),
        "requirements_locks": attr.label_keyed_string_dict(
            doc = "A dictionary mapping platform to requirement lock files.",
        ),
    },
)

requirements = module_extension(
    doc = """\
Module extension providing parsing of Python requirements files into
a hub repository containing an interface to a repository for
each requirement listed in the file.""",
    implementation = _requirements_impl,
    tag_classes = {
        "parse": _parse,
        "package_annotation": _annotation,
    },
)
