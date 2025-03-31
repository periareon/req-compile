"""Repository rules for downloading and extracting python wheel files"""

load(":annotation_utils.bzl", "deserialize_package_annotation")
load(":utils.bzl", "execute", "parse_artifact_name", "sanitize_package_name")

SDIST_ATTRS = {
    "sdist_deps_repos": attr.label_list(
        doc = "INTERNAL: DO NOT USE. Default dependencies for building source distributions.",
        default = [
            Label("@req_compile_sdist_compiler__pip//:pkg"),
            Label("@req_compile_sdist_compiler__setuptools//:pkg"),
            Label("@req_compile_sdist_compiler__wheel//:pkg"),
        ],
        allow_files = True,
    ),
    "_compiler": attr.label(
        allow_files = True,
        default = Label("//private:sdist_compiler.py"),
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
    # This makes this directory a top-level in the python import
    # search path for anything that depends on this.
    imports = ["."],
    deps = ["{pkg}"],
)
"""

_ENTRY_POINT_PYTHON_TEMPLATE = """\
{shebang}
import sys
from {module} import {attribute}
if __name__ == "__main__":
    sys.exit({attribute}())
"""

_BUILD_TEMPLATE = """\
load("@bazel_skylib//rules:copy_file.bzl", "copy_file")
load("@rules_req_compile//private:utils.bzl", "whl_repo_name")
load("@rules_python//python:defs.bzl", "py_library", "py_binary")

package(default_visibility = ["//visibility:public"])

DEPS_LABELS = {deps_labels}

DEPS_PACKAGES = {deps_packages}

py_library(
    name = "{name}",
    srcs = {srcs} + glob(
        include = ["site-packages/**/*.py"],
        exclude = {srcs_exclude},
        # Empty sources are allowed to support wheels that don't have any
        # pure-Python code, e.g. pymssql, which is written in Cython.
        allow_empty = True,
    ),
    data = {data} + glob(
        include = ["site-packages/**/*"],
        exclude = {data_exclude},
        allow_empty = True,
    ),
    # This makes this directory a top-level in the python import
    # search path for anything that depends on this.
    imports = ["site-packages"],
    deps = DEPS_LABELS + ["@{{}}//:pkg".format(whl_repo_name("{spoke_prefix}", dep)) for dep in DEPS_PACKAGES],
    tags = {tags},
    target_compatible_with = {target_compatible_with},
)

alias(
    name = "pkg",
    actual = "{name}",
)

filegroup(
    name = "whl",
    srcs = ["{whl_name}"],
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

def _generate_entry_point_rule(*, name, script, pkg):
    """Generate a Bazel `py_binary` rule for an entry point script.

    Note that the script is used to determine the name of the target. The name of
    entry point targets should be unique to avoid conflicts with existing sources or
    directories within a wheel.

    Args:
        name (str): The name of the generated py_binary.
        script (str): The path to the entry point's python file.
        pkg (str): The package owning the entry point. This is expected to
            match up with the `py_library` defined for each repository.

    Returns:
        str: A `py_binary` instantiation.
    """
    return _ENTRY_POINT_RULE_TEMPLATE.format(
        name = name,
        src = script.replace("\\", "/"),
        pkg = pkg,
    )

def _parse_entry_points_txt(content):
    console_scripts = {}
    capturing = False
    for line in content.splitlines():
        if "[console_scripts]" in line:
            capturing = True

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
            "file:///{}".format(whl_file),
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

    # Parse deps from annotations
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
    package_deps = additive_deps + [
        sanitize_package_name(dep)
        for dep in repository_ctx.attr.deps
        if dep not in negative_deps
    ]

    label_deps = [
        dep
        for dep in annotations.deps
        if dep.startswith(("@", "//"))
    ]

    data = annotations.data
    srcs = []
    srcs_exclude = annotations.srcs_exclude_glob
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

    target_compatible_with = "None"
    if repository_ctx.attr.constraint:
        target_compatible_with = "select({" + repr(repository_ctx.attr.constraint) + ": [], \"//conditions:default\": [\"@platforms//:incompatible\"]})"

    build_content = []

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

    for entry_point, entry_point_data in entry_points.items():
        entry_point_target_name = (
            _WHEEL_ENTRY_POINT_PREFIX + "_" + entry_point
        )
        entry_point_script_name = entry_point_target_name + ".py"
        repository_ctx.file(
            entry_point_script_name,
            _generate_entry_point_contents(entry_point_data.module, entry_point_data.attribute),
        )
        build_content.append(_generate_entry_point_rule(
            name = "{}_{}".format(_WHEEL_ENTRY_POINT_PREFIX, entry_point),
            script = entry_point_script_name,
            pkg = ":" + repository_ctx.attr.package,
        ))

    for src, dest in annotations.copy_srcs.items():
        srcs.append(dest)
        build_content.append(_generate_copy_commands(src, dest))

    for src, dest in annotations.copy_files.items():
        data.append(dest)
        build_content.append(_generate_copy_commands(src, dest))

    for src, dest in annotations.copy_executables.items():
        data.append(dest)
        build_content.append(
            _generate_copy_commands(src, dest, is_executable = True),
        )

    additive_content = ""
    if annotations.additive_build_file_content:
        additive_content += annotations.additive_build_file_content
    if annotations.additive_build_file:
        additive_build_path = repository_ctx.path(Label(annotations.additive_build_file))
        additive_content += repository_ctx.read(additive_build_path)

    build_content = [_BUILD_TEMPLATE.format(
        spoke_prefix = repository_ctx.attr.spoke_prefix,
        name = repository_ctx.attr.package,
        srcs = srcs,
        srcs_exclude = repr(srcs_exclude),
        data = repr(data),
        data_exclude = repr(data_exclude),
        deps_labels = json.encode_indent(label_deps, indent = " " * 4),
        deps_packages = json.encode_indent(package_deps, indent = " " * 4),
        tags = repr([]),
        target_compatible_with = target_compatible_with,
        whl_name = whl_name,
    )] + build_content

    repository_ctx.file("BUILD.bazel", "\n".join(build_content) + additive_content)

    return {
        "annotations": repository_ctx.attr.annotations,
        "constraint": repository_ctx.attr.constraint,
        "deps": repository_ctx.attr.deps,
        "interpreter": repository_ctx.attr.interpreter,
        "name": repository_ctx.name,
        "package": repository_ctx.attr.package,
        "patches": repository_ctx.attr.patches,
        "sdist_deps_repos": repository_ctx.attr.sdist_deps_repos,
        "sha256": whl_sha256,
        "spoke_prefix": repository_ctx.attr.spoke_prefix,
        "urls": repository_ctx.attr.urls,
        "version": repository_ctx.attr.version,
        "whl": repository_ctx.attr.whl,
    }

whl_repository = repository_rule(
    doc = """\
A repository rule for extracting a python [wheel](https://peps.python.org/pep-0491/) and defining a `py_library`.

This repository is expected to be generated by [py_requirements_repository](#py_requirements_repository).
""",
    implementation = _whl_repository_impl,
    attrs = {
        "annotations": attr.string(
            doc = "See [py_requirements_repository.annotation](#py_requirements_repository.annotation)",
            default = "{}",
        ),
        "constraint": attr.string(
            doc = "An optional constraint to assign to `target_compatible_with` where all other configurations will be invalid.",
        ),
        "deps": attr.string_list(
            doc = "A list of python package names that the current package depends on.",
            mandatory = True,
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
        "spoke_prefix": attr.string(
            doc = "The name of the [py_requirements_repository](#py_requirements_repository) plus a friendly platform suffix.",
            mandatory = True,
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
