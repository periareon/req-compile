"""Repository rules for downloading and extracting python wheel files"""

load(":annotation_utils.bzl", "deserialize_package_annotation")
load(":utils.bzl", "execute", "parse_artifact_name", "sanitize_package_name")

SDIST_ATTRS = {
    "sdist_deps_repos": attr.label_list(
        doc = "INTERNAL: DO NOT USE. Default dependencies for building source distributions.",
        default = [
            Label("@req_compile_sdist_compiler__pip//:pip"),
            Label("@req_compile_sdist_compiler__setuptools//:setuptools"),
            Label("@req_compile_sdist_compiler__wheel//:wheel"),
        ],
        allow_files = True,
    ),
    "_compiler": attr.label(
        allow_files = True,
        default = Label("//req_compile/private:sdist_compiler.py"),
    ),
}

def load_sdist_data(repository_ctx, data_file):
    data = json.decode(repository_ctx.read(data_file))
    return struct(
        wheel = data["wheel"],
        sha256 = data["sha256"],
    )

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

def _build_sdist(repository_ctx, sdist_file):
    repository_ctx.report_progress("Building wheel")

    if not repository_ctx.attr.interpreter:
        fail("A Python interpreter is required to build source distributions. " +
             "Pass a Python binary via the interpreter_* args to your `py_requirements_repository` or `parse` module tags.")
    interpreter = repository_ctx.path(repository_ctx.attr.interpreter)
    compiler = repository_ctx.path(repository_ctx.attr._compiler)

    data_file = repository_ctx.path("whl.json")

    pythonpath = ["."] + [
        whl_repo_to_python_path(repository_ctx, repo)
        for repo in repository_ctx.attr.sdist_deps_repos
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

    return load_sdist_data(repository_ctx, data_file)

_WHEEL_ENTRY_POINT_PREFIX = "entry_point"

_COPY_FILE_TEMPLATE = """\
copy_file(
    name = "{dest}.copy",
    src = "{src}",
    out = "{dest}",
    is_executable = {is_executable},
)
"""

_ENTRY_POINT_RULE_TEMPLATE = """\
py_binary(
    name = "{name}",
    srcs = ["{src}"],
    main = "{src}",
    deps = [":{pkg}"],
    tags = {tags},
)
"""

_ENTRY_POINT_PYTHON_TEMPLATE = """\
{shebang}
import sys
from {module} import {attribute}
if __name__ == "__main__":
    sys.exit({attribute}())
"""

# The root package of the repository holds the contents of the wheel. It is
# independent of any hub so that the same repository can be shared by every hub
# that pins this exact wheel.
#
# Every target is tagged `pypi_name=<package>` and `pypi_version=<version>`,
# the tags rules_python puts on the targets of a wheel, so that a target found
# by `bazel query` or `cquery` identifies its package without decoding the
# repository name, and tooling that reads those tags works with either.
_ROOT_BUILD_TEMPLATE = """\
load("@bazel_skylib//rules:copy_file.bzl", "copy_file")
load("@rules_venv//python:defs.bzl", "py_binary", "py_library")

package(default_visibility = ["//visibility:public"])

exports_files({entry_point_scripts})

# The Python modules of the wheel.
_SRCS = {srcs} + glob(
    include = ["site-packages/**/*.py"],
    exclude = {srcs_exclude},
    # Empty sources are allowed to support wheels that don't have any
    # pure-Python code, e.g. pymssql, which is written in Cython.
    allow_empty = True,
)

# Everything else the wheel installs.
_DATA = {data} + glob(
    include = ["site-packages/**/*"],
    exclude = {data_exclude},
    allow_empty = True,
)

# The contents of the wheel, deliberately without the Python packages it
# depends on. This repository is shared by every hub pinning this exact
# wheel, and each hub may have resolved those packages differently, so none
# can be named here. The only dependencies are labels an annotation added,
# which do not depend on a hub. Each hub gets a target below with the
# packages it resolved, and that is what the hub's `@<hub>//{name}` alias
# points at. Depend on the hub.
py_library(
    name = "{name}",
    srcs = _SRCS,
    data = _DATA,
    # This makes this directory a top-level in the python import
    # search path for anything that depends on this.
    imports = ["site-packages"],
    deps = {deps_labels},
    tags = {tags},
)

filegroup(
    name = "whl",
    srcs = ["{whl_name}"],
    tags = {tags},
)
"""

# The library of one hub. It owns the modules rather than depending on the
# library of the package, so that tools analyzing a library together with its
# dependencies, such as a type checker, see the modules with the dependencies
# of this hub instead of with none. It lives in the root package because the
# modules can only be globbed from there.
_HUB_LIBRARY_TEMPLATE = """\
# The wheel with the dependencies the `{hub}` hub resolved for it.
py_library(
    name = "{hub}.{name}",
    srcs = _SRCS,
    data = _DATA,
    imports = ["site-packages"],
    deps = {deps},
    tags = {tags},
)
"""

# A hub that resolved no dependencies for the wheel sees the library of the
# package itself. The two would otherwise be identical.
_HUB_ALIAS_TEMPLATE = """\
# The `{hub}` hub resolved no dependencies for the wheel.
alias(
    name = "{hub}.{name}",
    actual = ":{name}",
    tags = {tags},
)
"""

def _generate_copy_commands(src, dest, is_executable = False):
    """Generate a [@bazel_skylib//rules:copy_file.bzl%copy_file][cf] target

    [cf]: https://github.com/bazelbuild/bazel-skylib/blob/1.1.1/docs/copy_file_doc.md

    Args:
        src (str): The label for the `src` attribute of [copy_file][cf]
        dest (str): The label for the `out` attribute of [copy_file][cf]
        is_executable (bool, optional): Whether or not the file being copied is executable.
            sets `is_executable` for [copy_file][cf]

    Returns:
        str: A `copy_file` instantiation.
    """
    return _COPY_FILE_TEMPLATE.format(
        src = src,
        dest = dest,
        is_executable = is_executable,
    )

def _generate_entry_point_contents(
        module,
        attribute,
        shebang = "#!/usr/bin/env python3"):
    """Generate the contents of an entry point script.

    Args:
        module (str): The name of the module to use.
        attribute (str): The name of the attribute to call.
        shebang (str, optional): The shebang to use for the entry point python
            file.

    Returns:
        str: A string of python code.
    """
    contents = _ENTRY_POINT_PYTHON_TEMPLATE.format(
        shebang = shebang,
        module = module,
        attribute = attribute,
    )
    return contents

def _generate_entry_point_rule(*, name, script, pkg, tags):
    """Generate a Bazel `py_binary` rule for an entry point script.

    Note that the script is used to determine the name of the target. The name of
    entry point targets should be unique to avoid conflicts with existing sources or
    directories within a wheel.

    Args:
        name (str): The name of the generated py_binary.
        script (str): The label of the entry point's python file.
        pkg (str): The name of the library the entry point runs against, the
            target of the hub the entry point belongs to.
        tags (str): The rendered `tags` of every target of the repository.

    Returns:
        str: A `py_binary` instantiation.
    """
    return _ENTRY_POINT_RULE_TEMPLATE.format(
        name = name,
        src = script.replace("\\", "/"),
        pkg = pkg,
        tags = tags,
    )

def _parse_entry_points_txt(content):
    console_scripts = {}
    capturing = False
    for line in content.splitlines():
        if "[console_scripts]" in line:
            capturing = True
            continue

        if capturing:
            if not line.strip():
                continue

            if line.startswith("["):
                break

            name, _, data = line.strip().partition("=")
            module, _, attribute = data.strip().partition(":")
            console_scripts.update({
                name.strip(): struct(
                    module = module,
                    attribute = attribute,
                ),
            })

    return console_scripts

def hub_deps(hub, hub_data, annotations):
    """The Python packages a hub resolved for this wheel, as labels into the hub.

    Args:
        hub (str): The name of the hub.
        hub_data (dict): The `locks` of the hub using this wheel, a mapping of lock
            id to a dict with the `deps` the lock resolved for this wheel and the
            `config_setting` the hub uses to select the lock, which is None when the
            hub has a single lock, and the `default_lock` of the hub, if any.
        annotations (struct): The deserialized annotations of the package.

    Returns:
        struct: With `branches`, a mapping of the config setting selecting a lock
            to the sorted dependency labels of that lock, keyed by None when the hub
            has a single lock; `default`, the labels of the lock the hub falls back
            to, or None; and `empty`, whether no lock resolved any dependency.
    """
    negative_deps = [
        sanitize_package_name(dep[1:])
        for dep in annotations.deps
        if dep.startswith("-")
    ] + [
        sanitize_package_name(dep)
        for dep in annotations.deps_excludes
    ]
    additive_deps = [
        sanitize_package_name(dep)
        for dep in annotations.deps
        if not dep.startswith(("-", "@", "//"))
    ]

    branches = {}
    default_labels = None
    for lock_id, lock_data in hub_data["locks"].items():
        deps = additive_deps + [
            sanitize_package_name(dep)
            for dep in lock_data["deps"]
            if sanitize_package_name(dep) not in negative_deps
        ]
        labels = [
            "@{}//{}".format(hub, dep)
            for dep in sorted(depset(deps).to_list())
        ]
        branches[lock_data["config_setting"]] = labels
        if lock_id == hub_data.get("default_lock"):
            default_labels = labels

    if None in branches and len(branches) != 1:
        fail("Hub `{}` mixes locks with and without a config setting.".format(hub))

    return struct(
        branches = branches,
        default = default_labels,
        empty = not [labels for labels in branches.values() if labels],
    )

def render_deps(labels, deps):
    """Render the `deps` attribute of the library a hub sees for this wheel.

    Args:
        labels (list[str]): Dependencies that do not depend on the hub, the labels
            an annotation added.
        deps (struct): The hub's dependencies, see `hub_deps`.

    Returns:
        str: Starlark source, a list or a list added to a `select`.
    """
    if None in deps.branches:
        return json.encode_indent(labels + deps.branches[None], indent = " " * 4)

    lines = ["{} + select({{".format(json.encode(labels))]
    for config_setting, branch in deps.branches.items():
        lines.append("    \"{}\": {},".format(config_setting, json.encode(branch)))

    # When the hub falls back to this wheel on a platform none of its locks
    # match, the dependencies of the fallback lock apply as well.
    if deps.default != None:
        lines.append("    \"//conditions:default\": {},".format(json.encode(deps.default)))
    lines.append("})")
    return "\n".join(lines)

def _whl_repository_impl(repository_ctx):
    if not repository_ctx.attr.urls and not repository_ctx.attr.whl:
        fail("`urls` or `whl` must be provided. Please update {}".format(
            repository_ctx.name,
        ))

    repository_ctx.file("WORKSPACE.bazel", """workspace(name = "{}")""".format(
        repository_ctx.name,
    ))

    if repository_ctx.attr.whl:
        whl_file = repository_ctx.path(repository_ctx.attr.whl)
        whl_name = whl_file.basename

        whl_result = repository_ctx.download(
            "file://localhost/{}".format(whl_file),
            output = whl_name,
            sha256 = repository_ctx.attr.sha256,
        )
        whl_sha256 = whl_result.sha256
    else:
        whl_name = parse_artifact_name(repository_ctx.attr.urls)
        if not whl_name:
            fail("Failed to parse wheel names for {} from {}".format(
                repository_ctx.name,
                repository_ctx.attr.urls,
            ))

        whl_result = repository_ctx.download(
            repository_ctx.attr.urls,
            output = whl_name,
            sha256 = repository_ctx.attr.sha256,
        )
        whl_sha256 = whl_result.sha256

        if not whl_name.endswith(".whl"):
            sdist_info = _build_sdist(repository_ctx, whl_name)
            whl_name = sdist_info.wheel

    # Unfortunately `repository_ctx.extract` does not allow us to dictate
    # the type of the archive. So in order to get Bazel to extract a wheel
    # the archive must be renamed to `.zip`.
    repository_ctx.symlink(
        whl_name,
        whl_name + ".zip",
    )
    repository_ctx.extract(
        whl_name + ".zip",
        output = "site-packages",
    )
    repository_ctx.delete(whl_name + ".zip")

    annotations = deserialize_package_annotation(repository_ctx.attr.annotations)

    patches = repository_ctx.attr.patches + [
        repository_ctx.path(Label(patch))
        for patch in annotations.patches
    ]
    for patch in patches:
        repository_ctx.patch(
            patch,
            strip = 1,
        )

    label_deps = [
        dep
        for dep in annotations.deps
        if dep.startswith(("@", "//"))
    ]

    data = list(annotations.data)
    srcs = []
    srcs_exclude = list(annotations.srcs_exclude_glob)
    data_exclude = [
        whl_name,
        "**/*.py",
        "**/*.pyc",
        "**/*.pyc.*",  # During pyc creation, temp files named *.pyc.NNNN are created
        # RECORD is known to contain sha256 checksums of files which might include the checksums
        # of generated files produced when wheels are installed. The file is ignored to avoid
        # Bazel caching issues.
        "**/*.dist-info/RECORD",
    ] + annotations.data_exclude_glob

    root_content = []

    # Find the `dist-info` directory
    dist_info_dir = None
    platlib_dir = None
    site_packages = repository_ctx.path("./site-packages")
    for entry in site_packages.readdir():
        if entry.basename.endswith(".dist-info"):
            dist_info_dir = entry
        if entry.basename.endswith("-{}.data".format(repository_ctx.attr.version)):
            for sub_entry in entry.readdir():
                if sub_entry.basename == "platlib":
                    platlib_dir = sub_entry
                    break

    if not dist_info_dir:
        fail("Failed to find dist-info directory.")

    # https://peps.python.org/pep-0427/#what-s-the-deal-with-purelib-vs-platlib
    # platlib wheels are expected to have the data directory extracted out to the standard
    # purelib location. This is mostly handled here by symlinking the contents into the
    # correct location and exlcuding the original location from the glob patterns.
    # Symlinking is only used because `repository_ctx` has no "move" functionality.
    if platlib_dir:
        _, _, site_dir = str(platlib_dir).partition(str(site_packages))
        exclude = "site-packages/{}/**".format(site_dir.strip("/"))
        data_exclude.append(exclude)
        srcs_exclude.append(exclude)
        for entry in platlib_dir.readdir():
            repository_ctx.symlink(entry, "{}/{}".format(site_packages, entry.basename))

    # Check for an entry_points.txt
    entry_points = {}
    entry_points_path = dist_info_dir.get_child("entry_points.txt")
    if entry_points_path.exists:
        entry_points_content = repository_ctx.read(entry_points_path)
        entry_points = _parse_entry_points_txt(entry_points_content)

    entry_point_scripts = []
    for entry_point, entry_point_data in entry_points.items():
        entry_point_script_name = "{}_{}.py".format(_WHEEL_ENTRY_POINT_PREFIX, entry_point)
        repository_ctx.file(
            entry_point_script_name,
            _generate_entry_point_contents(entry_point_data.module, entry_point_data.attribute),
        )
        entry_point_scripts.append(entry_point_script_name)

    for src, dest in annotations.copy_srcs.items():
        srcs.append(dest)
        root_content.append(_generate_copy_commands(src, dest))

    for src, dest in annotations.copy_files.items():
        data.append(dest)
        root_content.append(_generate_copy_commands(src, dest))

    for src, dest in annotations.copy_executables.items():
        data.append(dest)
        root_content.append(
            _generate_copy_commands(src, dest, is_executable = True),
        )

    additive_content = ""
    if annotations.additive_build_file_content:
        additive_content += annotations.additive_build_file_content
    if annotations.additive_build_file:
        additive_build_path = repository_ctx.path(Label(annotations.additive_build_file))
        additive_content += repository_ctx.read(additive_build_path)

    hubs = json.decode(repository_ctx.attr.hubs)
    package_name = sanitize_package_name(repository_ctx.attr.package)

    # The tags of every target, see `_ROOT_BUILD_TEMPLATE`.
    tags = json.encode_indent([
        "manual",
        "pypi_name={}".format(repository_ctx.attr.package),
        "pypi_version={}".format(repository_ctx.attr.version),
    ], indent = " " * 4)

    root_content = [_ROOT_BUILD_TEMPLATE.format(
        name = package_name,
        tags = tags,
        entry_point_scripts = json.encode(sorted(entry_point_scripts)),
        srcs = srcs,
        srcs_exclude = repr(srcs_exclude),
        data = repr(data),
        data_exclude = repr(data_exclude),
        deps_labels = json.encode_indent(label_deps, indent = " " * 4),
        whl_name = whl_name,
    )] + root_content

    # The library of a hub only differs from the library of the package by the
    # dependencies the hub resolved. Without any, the hub aliases the package.
    for hub, hub_data in hubs.items():
        deps = hub_deps(hub, hub_data, annotations)
        if deps.empty:
            root_content.append(_HUB_ALIAS_TEMPLATE.format(
                hub = hub,
                name = package_name,
                tags = tags,
            ))
        else:
            root_content.append(_HUB_LIBRARY_TEMPLATE.format(
                hub = hub,
                name = package_name,
                deps = render_deps(label_deps, deps),
                tags = tags,
            ))
        for entry_point in sorted(entry_points):
            root_content.append(_generate_entry_point_rule(
                name = "{}.{}_{}".format(hub, _WHEEL_ENTRY_POINT_PREFIX, entry_point),
                script = "{}_{}.py".format(_WHEEL_ENTRY_POINT_PREFIX, entry_point),
                pkg = "{}.{}".format(hub, package_name),
                tags = tags,
            ))

    repository_ctx.file("BUILD.bazel", "\n".join(root_content) + additive_content)

    return {
        "annotations": repository_ctx.attr.annotations,
        "hubs": repository_ctx.attr.hubs,
        "interpreter": repository_ctx.attr.interpreter,
        "name": repository_ctx.name,
        "package": repository_ctx.attr.package,
        "patches": repository_ctx.attr.patches,
        "sdist_deps_repos": repository_ctx.attr.sdist_deps_repos,
        "sha256": whl_sha256,
        "urls": repository_ctx.attr.urls,
        "version": repository_ctx.attr.version,
        "whl": repository_ctx.attr.whl,
    }

whl_repository = repository_rule(
    doc = """\
A repository rule for extracting a python [wheel](https://peps.python.org/pep-0491/) and defining a `py_library`.

This repository is expected to be generated by [py_requirements_repository](#py_requirements_repository).

The repository contains the wheel (`//:whl`), a `py_library` named after the package (`//:requests`) holding its
files but none of its dependencies, and a target per hub using the wheel (`//:pip_deps.requests`) holding its files
with the dependencies that hub resolved for the package, or aliasing the package when the hub resolved none. The
console scripts of the wheel are a `py_binary` per hub (`//:pip_deps.entry_point_<script>`). This allows a single
repository to be shared by every hub that pins the same wheel, even when they resolved its dependencies differently.
""",
    implementation = _whl_repository_impl,
    attrs = {
        "annotations": attr.string(
            doc = "See [py_requirements_repository.annotation](#py_requirements_repository.annotation)",
            default = "{}",
        ),
        "hubs": attr.string(
            doc = (
                "A json encoded mapping of hub names to the hub's use of this wheel: its `locks`, a mapping " +
                "of lock id to the `deps` (python package names) resolved for the package and the " +
                "`config_setting` label the hub uses to select the lock, which is `null` for hubs with a " +
                "single lock, and the `default_lock` the hub falls back to, if any."
            ),
            default = "{}",
        ),
        "interpreter": attr.label(
            doc = "Optional Python interpreter binary to use for building sdists.",
        ),
        "package": attr.string(
            doc = "The name of the python package the wheel represents.",
            mandatory = True,
        ),
        "patches": attr.label_list(
            doc = "Patches to apply to the installed wheel.",
            allow_files = True,
        ),
        "sha256": attr.string(
            doc = "The expected SHA-256 of the file downloaded.",
        ),
        "urls": attr.string_list(
            doc = "A list of URLs to the python wheel.",
        ),
        "version": attr.string(
            doc = "The version of the python package.",
            mandatory = True,
        ),
        "whl": attr.label(
            doc = "The label to a wheel.",
        ),
    } | SDIST_ATTRS,
)
