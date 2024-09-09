"""Python requirements module extension."""

load(
    "//:defs.bzl",
    package_annotation = "py_package_annotation",
)
load(
    "//private:reqs_repo.bzl",
    "create_spoke_repos",
    "parse_requirements_locks",
    "py_requirements_repository",
)

def _requirements_impl(ctx):
    """Process annotations and parse tags."""
    annotations = {}

    override_module_repos = {}

    # Gather all annotations first.
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
        for parse in mod.tags.parse:
            if mod.is_root and parse.override_module_repos:
                for override_mod, override_repos in parse.override_module_repos.items():
                    if override_mod in override_module_repos:
                        fail("Module {} already has overrides from this module.".format(
                            override_mod,
                        ))
                override_module_repos[override_mod] = struct(hub_name = parse.name, override_repos = list(override_repos))

    # Create hubs for each parse tag.
    for mod in ctx.modules:
        for parse in mod.tags.parse:
            # Determine the interpreter to use, if provided. This is required for
            # source dists.
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

            if mod.name in override_module_repos and parse.name in override_module_repos[mod.name].override_repos:
                py_requirements_repository(
                    name = parse.name,
                    hub_name = override_module_repos[mod.name].hub_name,
                    requirements_lock = parse.requirements_lock,
                    requirements_locks = parse.requirements_locks,
                    interpreter = interpreter,
                )
                override_module_repos[mod.name].override_repos.remove(parse.name)
                continue

            py_requirements_repository(
                name = parse.name,
                hub_name = parse.name,
                requirements_lock = parse.requirements_lock,
                requirements_locks = parse.requirements_locks,
                interpreter = interpreter,
            )
            platform_packages = parse_requirements_locks(
                hub_name = parse.name,
                ctx = ctx,
                attrs = parse,
                annotations = annotations,
            )
            for defs_id, data in platform_packages.items():
                spoke_prefix = parse.name
                if defs_id:
                    spoke_prefix += "_" + defs_id
                create_spoke_repos(spoke_prefix, data.packages, interpreter)

    for mod in sorted(override_module_repos):
        repos = override_module_repos[mod].override_repos
        if repos:
            fail("Module \"{}\" does not create repos \"{}\"".format(mod, "\", \"".join(sorted(repos))))

_annotation = tag_class(
    doc = """\
A tag representing a annotation editing a Python package.

See [@rules_python//python:pip.bzl%package_annotation](https://github.com/bazelbuild/rules_python/blob/main/docs/pip_repository.md#package_annotation)
for more information.
""",
    attrs = {
        "additive_build_file": attr.label(),
        "additive_build_file_content": attr.string(),
        "copy_executables": attr.string_dict(),
        "copy_files": attr.string_dict(),
        "copy_srcs": attr.string_dict(),
        "data": attr.string_list(),
        "data_exclude_glob": attr.string_list(),
        "deps": attr.string_list(),
        "deps_excludes": attr.string_list(),
        "package": attr.string(),
        "patches": attr.label_list(),
        "srcs_exclude_glob": attr.string_list(),
    },
)

_parse = tag_class(
    doc = """"\
Parse a lock file into a hub repo.

A hub repo is a single repository that can be pulled into a
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
        "interpreter_linux": attr.label(
            doc = "Optional Linux amd64 Python interpreter binary to use for sdists.",
        ),
        "interpreter_macos_aarch64": attr.label(
            doc = "Optional MacOS ARM Python interpreter binary to use for sdists.",
        ),
        "interpreter_macos_intel": attr.label(
            doc = "Optional MacOS intel Python interpreter binary to use for sdists.",
        ),
        "interpreter_windows": attr.label(
            doc = "Optional Windows x64 Python interpreter binary to use for sdists.",
        ),
        "name": attr.string(
            doc = "Name of the hub repository to create.",
            mandatory = True,
        ),
        "requirements_lock": attr.label(
            doc = "A single lockfile for a single platform solution.",
        ),
        "requirements_locks": attr.label_keyed_string_dict(
            doc = "A dictionary mapping platform to requirement lock files.",
        ),
        "override_module_repos": attr.string_list_dict(
            doc = """\
Mapping of module name to list of repos that should be overridden by this hub. The repos
must be those that are expected to be created by this module extension.

The overridden hub will attempt to map all of its requirements to the root module's hub, meaning
the root module hub must be a superset of the overridden hub.

This attribute is intended to have the root module coordinate all Python packages such
that Python libraries from dependencies can be safely imported into the same interpreter.
Do not override repos for libraries that will never be mixed. To inject Python dependencies
for use in most child modules, a custom toolchain type is most appropriate.""",
            default = {},
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
        "package_annotation": _annotation,
        "parse": _parse,
    },
)
