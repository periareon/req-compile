"""Python requirements module extension."""

load(
    "//:defs.bzl",
    package_annotation = "py_package_annotation",
)
load(
    "//private:reqs_repo.bzl",
    "create_hub_repos",
    "hub_spec",
    "lock_spec",
    "plan_hubs",
)

def _interpreter_for_host(ctx, parse):
    """The interpreter of a `parse` tag matching the host, used to build sdists."""
    if ctx.os.name == "mac os x":
        if ctx.os.arch == "amd64":
            return parse.interpreter_macos_x86_64
        return parse.interpreter_macos_aarch64
    if ctx.os.name == "linux":
        if ctx.os.arch == "amd64":
            return parse.interpreter_linux_x86_64
        return parse.interpreter_linux_aarch64
    if ctx.os.name.startswith("windows"):
        return parse.interpreter_windows
    return None

def _is_label_string(value):
    """Whether a `requirements_locks` value is a label (the deprecated form) rather than an id."""
    return value.startswith(("@", "//", ":")) or "//" in value

def _legacy_constraint_label(lock, constraint):
    """Resolve the string constraint of the deprecated `requirements_locks` form."""

    # If the constraint is a workspace relative label, assume
    # the lock (which is a key in an `attr.label_keyed_string_dict`
    # ) has the desired fully resolved workspace name.
    if not constraint.startswith("@"):
        workspace, _, _ = str(lock).partition("//")
        constraint = "{}{}".format(workspace, constraint)
    return Label(constraint)

def _is_default_condition(label):
    """Whether a `config_settings` key is `//conditions:default`."""
    return label.package == "conditions" and label.name == "default"

def _hub_locks(mod, parse):
    """Build the `lock_spec`s of a `parse` tag.

    Locks and the config settings selecting them are both label keyed, which lets Bazel
    resolve each in the module defining the hub. They are joined by the id they map to.
    """
    locks = []
    if parse.requirements_lock:
        locks.append(lock_spec(file = parse.requirements_lock))

    settings = {}
    default = None
    for label, lock_id in parse.config_settings.items():
        if _is_default_condition(label):
            if default:
                fail("Hub `{}` of module `{}` maps `//conditions:default` to both `{}` and `{}`.".format(
                    parse.name,
                    mod.name,
                    default,
                    lock_id,
                ))
            default = lock_id
            continue
        if lock_id in settings:
            fail((
                "Hub `{}` of module `{}` maps both `{}` and `{}` to the lock `{}`. Combine them into a " +
                "single `config_setting_group` instead."
            ).format(parse.name, mod.name, settings[lock_id], label, lock_id))
        settings[lock_id] = label

    # Once any lock is mapped to a config setting, every lock must be. Mixing
    # explicit settings with settings derived from lock headers hides overlaps.
    explicit = bool(settings)

    ids = {}
    unmapped = []
    for lock, value in parse.requirements_locks.items():
        if _is_label_string(value):
            locks.append(lock_spec(
                file = lock,
                config_setting = _legacy_constraint_label(lock, value),
            ))
            continue
        if value in ids:
            fail("Hub `{}` of module `{}` maps both `{}` and `{}` to the lock id `{}`.".format(
                parse.name,
                mod.name,
                ids[value],
                lock,
                value,
            ))
        if value:
            ids[value] = lock
        config_setting = settings.pop(value, None) if value else None
        if explicit and not config_setting:
            unmapped.append("{} ({})".format(lock, value or "no id"))
        locks.append(lock_spec(
            file = lock,
            id = value or None,
            config_setting = config_setting,
            default = bool(value) and default == value,
        ))

    if unmapped:
        fail((
            "Hub `{}` of module `{}` maps some locks to config settings but not all of them. Either map " +
            "every lock in `config_settings` or none, in which case the platform recorded in each lock's " +
            "header is used. Missing: {}"
        ).format(parse.name, mod.name, ", ".join(unmapped)))

    if default and default not in ids:
        fail("Hub `{}` of module `{}` maps `//conditions:default` to the unknown lock `{}`. Known locks: {}".format(
            parse.name,
            mod.name,
            default,
            ", ".join(sorted(ids)),
        ))
    if settings:
        fail("Hub `{}` of module `{}` has config settings for locks that do not exist: {}. Known locks: {}".format(
            parse.name,
            mod.name,
            ", ".join(["{} -> {}".format(label, lock_id) for lock_id, label in settings.items()]),
            ", ".join(sorted(ids)),
        ))

    return locks

def _collect_annotations(ctx):
    """Gather annotations from every module.

    The root module wins any disagreement. Other modules must agree with each other.
    """
    annotations = {}
    owners = {}
    for mod in ctx.modules:
        for annotation in mod.tags.package_annotation:
            data = package_annotation(
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
            if annotation.package in annotations and annotations[annotation.package] != data:
                if mod.is_root:
                    pass
                elif owners[annotation.package] == "<root>":
                    continue
                else:
                    fail("Module `{}` and module `{}` annotate the python package `{}` differently. Annotate it from the root module to decide.".format(
                        owners[annotation.package],
                        mod.name,
                        annotation.package,
                    ))
            annotations[annotation.package] = data
            owners[annotation.package] = "<root>" if mod.is_root else mod.name
    return annotations

def _requirements_impl(ctx):
    """Process annotations and parse tags."""
    annotations = _collect_annotations(ctx)

    hubs = {}
    override_module_repos = {}

    for mod in ctx.modules:
        for parse in mod.tags.parse:
            if parse.name in hubs:
                fail((
                    "The requirements hub `{}` is defined by both module `{}` and module `{}`. Hub names " +
                    "must be globally unique, rename one of them or use `override_module_repos` to have " +
                    "the root module provide it."
                ).format(parse.name, hubs[parse.name]["module"], mod.name))

            if parse.requirements_lock and parse.requirements_locks:
                fail("`requirements_lock` and `requirements_locks` are mutually exclusive. Please update hub `{}` of module `{}`.".format(
                    parse.name,
                    mod.name,
                ))

            hubs[parse.name] = {
                "alias_of": None,
                "interpreter": _interpreter_for_host(ctx, parse),
                "legacy_root_pkg_aliases": parse.legacy_root_pkg_aliases,
                "locks": _hub_locks(mod, parse),
                "module": mod.name,
                "package_aliases": parse.package_aliases,
            }

            if mod.is_root and parse.override_module_repos:
                for override_mod, override_repos in parse.override_module_repos.items():
                    if override_mod in override_module_repos:
                        fail("Module {} already has overrides from this module.".format(
                            override_mod,
                        ))
                    override_module_repos[override_mod] = struct(
                        hub_name = parse.name,
                        override_repos = list(override_repos),
                    )

    # Hubs of dependent modules that the root module provides instead.
    for override_mod, override in override_module_repos.items():
        for hub_name in override.override_repos:
            if hub_name not in hubs or hubs[hub_name]["module"] != override_mod:
                fail("Module \"{}\" does not create repos \"{}\"".format(override_mod, hub_name))
            if override.hub_name == hub_name:
                fail("Hub `{}` cannot override itself.".format(hub_name))
            hubs[hub_name]["alias_of"] = override.hub_name

    specs = {
        name: hub_spec(
            name = name,
            locks = hub["locks"],
            module = hub["module"],
            interpreter = hub["interpreter"],
            package_aliases = hub["package_aliases"],
            legacy_root_pkg_aliases = hub["legacy_root_pkg_aliases"],
            alias_of = hub["alias_of"],
        )
        for name, hub in hubs.items()
    }

    create_hub_repos(plan_hubs(ctx, specs, annotations))

    return ctx.extension_metadata(
        reproducible = True,
    )

_annotation = tag_class(
    doc = "A tag representing a annotation editing a Python package.",
    attrs = {
        "additive_build_file": attr.label(
            doc = "The label of a `BUILD` file to add to the generated one for a pacakge.",
        ),
        "additive_build_file_content": attr.string(
            doc = "Raw text to add to the generated `BUILD` file of a package.",
        ),
        "copy_executables": attr.string_dict(
            doc = "A mapping of `src` and `out` files for [@bazel_skylib//rules:copy_file.bzl](https://github.com/bazelbuild/bazel-skylib/blob/1.7.1/docs/copy_file_doc.md). Targets generated here will also be flagged as executable.",
        ),
        "copy_files": attr.string_dict(
            doc = "A mapping of `src` and `out` files for [@bazel_skylib//rules:copy_file.bzl](https://github.com/bazelbuild/bazel-skylib/blob/1.7.1/docs/copy_file_doc.md).",
        ),
        "copy_srcs": attr.string_dict(
            doc = "A mapping of `src` and `out` files for [@bazel_skylib//rules:copy_file.bzl](https://github.com/bazelbuild/bazel-skylib/blob/1.7.1/docs/copy_file_doc.md). The output files are added to the `py_library.srcs` attribute.",
        ),
        "data": attr.string_list(
            doc = "A list of labels to add as `data` dependencies to the generated `py_library` target.",
        ),
        "data_exclude_glob": attr.string_list(
            doc = "A list of exclude glob patterns to add as `data` to the generated `py_library` target.",
        ),
        "deps": attr.string_list(
            doc = "A list of labels to add as `data` dependencies to the generated `py_library` target.",
        ),
        "deps_excludes": attr.string_list(
            doc = "A list of exclude glob patterns to add as `data` to the generated `py_library` target.",
        ),
        "package": attr.string(
            doc = "The name of the package the annotations applies to.",
            mandatory = True,
        ),
        "patches": attr.label_list(
            doc = "A list of patch files to apply to the wheel.",
        ),
        "srcs_exclude_glob": attr.string_list(
            doc = "A list of labels to add as `srcs` to the generated `py_library` target.",
        ),
    },
)

_parse = tag_class(
    doc = """"\
Define a hub repository of Python requirements.

A hub repo is a single repository that can be pulled into a
module via `use_repo` and provides every Python package of its
lock files.

Every distinct wheel pinned by any hub, of any module, is downloaded once into a
repository shared by all the hubs using it. Hub names must therefore be unique
across all modules.

```python
requirements = use_extension("@rules_req_compile//extensions:python.bzl", "requirements")
requirements.parse(
    name = "pip_deps",
    requirements_locks = {
        "//3rdparty:requirements.linux_x86_64.txt": "linux_x86_64",
        "//3rdparty:requirements.macos_aarch64.txt": "macos_aarch64",
        "//3rdparty:requirements.windows_x86_64.txt": "windows_x86_64",
    },
)
use_repo(requirements, "pip_deps")
```

This example was a multi-platform set of solutions, pulled into a single
hub repository named "pip_deps". Each lock is given an id. The platform of
each lock is read from the header `req-compile` writes to lock files compiled
with the `platform` attribute of `py_reqs_compiler` (`## Platform: manylinux_2_28_x86_64`),
which selects on the operating system and CPU of that wheel platform tag.

To control exactly when a lock is used, map your own config settings to the
ids of the locks with `config_settings`. This is required when two locks share
a platform, e.g. the same operating system and CPU with different glibc floors:

```python
requirements.parse(
    name = "pip_deps",
    config_settings = {
        "//tools/constraints:linux": "linux",
        "//tools/constraints:macos": "macos",
        "@my_constraints//:windows_gpu": "windows",
        # Optionally, the lock used when nothing else matches.
        "//conditions:default": "linux",
    },
    requirements_locks = {
        "//3rdparty:requirements.linux.txt": "linux",
        "//3rdparty:requirements.macos.txt": "macos",
        "//3rdparty:requirements.windows.txt": "windows",
    },
)
```

Both dictionaries are keyed by labels, so the lock files and the config settings
are each resolved by the module defining the hub. Any `config_setting` or
`config_setting_group` visible to that module can be used, and the hub never
needs to see it: the hub aliases each setting and selects on the alias. Once
`config_settings` is used every lock must appear in it, mixing explicit settings
with platforms derived from headers is an error.

A hub whose locks do not all contain the same packages is supported. A package
missing from the lock of a platform is incompatible with that platform, so targets
depending on it are skipped there rather than failing to build.
""",
    attrs = {
        "config_settings": attr.label_keyed_string_dict(
            doc = (
                "A mapping of `config_setting` labels to the id of the lock in `requirements_locks` they " +
                "select. The special key `//conditions:default` names the lock used when no config setting " +
                "matches. When set, every lock must be mapped. When empty, locks are selected by the platform " +
                "recorded in their header."
            ),
            default = {},
        ),
        "interpreter_linux_aarch64": attr.label(
            doc = "Optional Linux arm64 Python interpreter binary to use for sdists.",
        ),
        "interpreter_linux_x86_64": attr.label(
            doc = "Optional Linux amd64 Python interpreter binary to use for sdists.",
        ),
        "interpreter_macos_aarch64": attr.label(
            doc = "Optional MacOS ARM Python interpreter binary to use for sdists.",
        ),
        "interpreter_macos_x86_64": attr.label(
            doc = "Optional MacOS x86_64 Python interpreter binary to use for sdists.",
        ),
        "interpreter_windows": attr.label(
            doc = "Optional Windows x64 Python interpreter binary to use for sdists.",
        ),
        "legacy_root_pkg_aliases": attr.bool(
            doc = (
                "If True, creates aliases in the root BUILD.bazel file pointing to the " +
                "package targets in their subpackages. This provides backward compatibility " +
                "for code that references packages at the root (e.g., `@repo//:package_name`)."
            ),
            default = False,
        ),
        "name": attr.string(
            doc = "Name of the hub repository to create. Must be unique across all modules.",
            mandatory = True,
        ),
        "override_module_repos": attr.string_list_dict(
            doc = """\
Mapping of module name to list of hubs that should be overridden by this hub. The hubs
must be those that are expected to be created by this module extension for that module.

Every package of the overridden hub becomes an alias of the same package in this hub,
meaning this hub must provide every package of the overridden hub.

This attribute is intended to have the root module coordinate all Python packages such
that Python libraries from dependencies can be safely imported into the same interpreter.
Do not override repos for libraries that will never be mixed. To inject Python dependencies
for use in most child modules, a custom toolchain type is most appropriate.""",
            default = {},
        ),
        "package_aliases": attr.label_keyed_string_dict(
            doc = """\
Map `py_library` targets to replace instances of the paired distribution when
used. This allows local source code to directly replaced a library which normally comes from
a downloaded wheel.""",
            default = {},
        ),
        "requirements_lock": attr.label(
            doc = "A single lockfile for a single platform solution.",
        ),
        "requirements_locks": attr.label_keyed_string_dict(
            doc = (
                "A mapping of lock files to an id naming each lock within the hub. Ids are matched against " +
                "`config_settings`; without `config_settings`, locks are selected by the platform recorded in " +
                "their header. An empty id derives the id from the header or file name. For compatibility, a " +
                "value that is a label string is treated as the config setting of the lock, but such labels are " +
                "resolved relative to `rules_req_compile` and can only name config settings visible to it."
            ),
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
