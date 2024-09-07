"""Utilities for applying annotations to Bazel python packages"""

load("@rules_cc//cc:defs.bzl", "CcInfo")

def _assert_absolute(label):
    """Ensure a given label is an absolute label

    Args:
        label (Label): The label to check
    """
    label_str = str(label)
    if not label_str.startswith("@"):
        fail("The labels must be absolute. Please update '{}'".format(
            label_str,
        ))

# Expected to satisfy the upstream `package_annotation` interface:
# https://github.com/bazelbuild/rules_python/blob/0.31.0/python/pip_install/pip_repository.bzl#L941-L965
def py_package_annotation(
        *,
        additive_build_file = None,
        additive_build_file_content = None,
        additive_build_content = None,
        copy_srcs = {},
        copy_files = {},
        copy_executables = {},
        data = [],
        data_exclude_glob = [],
        srcs_exclude_glob = [],
        deps = [],
        deps_excludes = [],
        patches = []):
    """Annotations to apply to the BUILD file content from package generated from a `pip_repository` rule.

    [cf]: https://github.com/bazelbuild/bazel-skylib/blob/main/docs/copy_file_doc.md

    Args:
        additive_build_file (Label, optional): The label of a `BUILD` file to add to the generated one for a pacakge.
        additive_build_file_content (str, optional): Raw text to add to the generated `BUILD` file of a package.
        additive_build_content (str, optional): __DEPRECATED__ use `additive_build_file_content` instead.
        copy_srcs (dict, optional): A mapping of `src` and `out` files for [@bazel_skylib//rules:copy_file.bzl][cf].
            The output files are added to the `py_library.srcs` attribute.
        copy_files (dict, optional): A mapping of `src` and `out` files for [@bazel_skylib//rules:copy_file.bzl][cf].
            The output files are added to the `py_library.data` attribute.
        copy_executables (dict, optional): A mapping of `src` and `out` files for
            [@bazel_skylib//rules:copy_file.bzl][cf]. Targets generated here will also be flagged as
            executable.
        data (list, optional): A list of labels to add as `data` dependencies to the generated `py_library` target.
        data_exclude_glob (list, optional): A list of exclude glob patterns to add as `data` to the generated
            `py_library` target.
        srcs_exclude_glob (list, optional): A list of labels to add as `srcs` to the generated `py_library` target.
        deps (list, optional): A list of dependencies to include to the package. Can be other packages or labels.
        deps_excludes (list, optional): A list of packages to exclude from the package. (In cases where a package
            has circular dependencies).
        patches (list, optional): A list of patch files to apply to the wheel.

    Returns:
        str: A json encoded string of the provided content.
    """
    if additive_build_file:
        _assert_absolute(additive_build_file)

    additive_content = ""
    if additive_build_file_content:
        additive_content += additive_build_file_content
    if additive_build_content:
        additive_content += additive_build_content

    str_patches = []
    for patch in patches:
        _assert_absolute(patch)
        str_patches.append(str(patch))

    # Ensure deps can be json serialized
    str_deps = []
    for dep in deps:
        if type(dep) == "Label":
            str_deps.append(str(dep))
        else:
            str_deps.append(dep)

    str_data = []
    for item in data:
        if type(item) == "Label":
            str_data.append(str(item))
        else:
            str_data.append(item)

    return json.encode(struct(
        additive_build_file = str(additive_build_file) if additive_build_file else None,
        additive_build_file_content = additive_content,
        copy_executables = copy_executables,
        copy_files = copy_files,
        copy_srcs = copy_srcs,
        data = str_data,
        data_exclude_glob = data_exclude_glob,
        deps = str_deps,
        deps_excludes = deps_excludes,
        patches = str_patches,
        srcs_exclude_glob = srcs_exclude_glob,
    ))

PyPackageAnnotatedTargetInfo = provider(
    doc = "Information about a target proudced by `py_package_annotations`.",
    fields = {
        "providers": "List[str]: A set of provider names found in `target`.",
        "target": "Target: The `py_package_annotation` defined target.",
    },
)

def _py_package_annotation_target_impl(ctx):
    providers = []
    if OutputGroupInfo in ctx.attr.target:
        providers.append("OutputGroupInfo")
    if InstrumentedFilesInfo in ctx.attr.target:
        providers.append("InstrumentedFilesInfo")
    if CcInfo in ctx.attr.target:
        providers.append("CcInfo")

    # Note that `DefaulInfo` is not returned here so that these
    # targets do not contirbute runfiles to the python target.
    return [PyPackageAnnotatedTargetInfo(
        target = ctx.attr.target,
        providers = sorted(depset(providers).to_list()),
    )]

py_package_annotation_target = rule(
    doc = "A container for targets defined by `py_package_annotation` data applied to a python package.",
    implementation = _py_package_annotation_target_impl,
    attrs = {
        "target": attr.label(
            doc = "The target to track in a python package.",
            mandatory = True,
            allow_files = True,
        ),
    },
)

PyPackageAnnotatedTargetsInfo = provider(
    doc = "Info about all `py_package_annotation` targets found on a python package.",
    fields = {
        "targets": "Depset[PyPackageAnnotatedTargetInfo]: A list of annotation defined targets.",
    },
)

def _py_package_annotation_deps_aspect_impl(target, ctx):
    if PyPackageAnnotatedTargetsInfo in target:
        return []

    targets = []
    for data in ctx.rule.attr.data:
        if PyPackageAnnotatedTargetInfo in data:
            targets.append(data[PyPackageAnnotatedTargetInfo])

    return [PyPackageAnnotatedTargetsInfo(
        targets = depset(targets),
    )]

py_package_annotation_deps_aspect = aspect(
    doc = "An aspect for locating `py_package_annotation_dep` targets.",
    implementation = _py_package_annotation_deps_aspect_impl,
)

def _py_package_annotation_consumer_impl(ctx):
    info = None
    available = []
    for data in ctx.attr.package[PyPackageAnnotatedTargetsInfo].targets.to_list():
        available.append(data.target.label.name)
        if data.target.label.name == ctx.attr.consume:
            info = data
            break

    if not info:
        fail("Failed to find python package annotation target `{}` on `{}`. Available: {}".format(
            ctx.attr.consume,
            ctx.attr.package.label,
            sorted(depset(available).to_list()),
        ))

    # TODO: Default info changes behavior when it's simply forwarded.
    # To avoid this a new one is recreated.
    default_info = DefaultInfo(
        files = info.target[DefaultInfo].files,
        runfiles = info.target[DefaultInfo].default_runfiles,
    )

    providers = []
    if "OutputGroupInfo" in info.providers:
        providers.append(info.target[OutputGroupInfo])
    if "InstrumentedFilesInfo" in info.providers:
        providers.append(info.target[InstrumentedFilesInfo])
    if "CcInfo" in info.providers:
        providers.append(info.target[CcInfo])

    return [default_info] + providers

py_package_annotation_consumer = rule(
    doc = "A rule for parsing `annotation_data` targets from a python target.",
    implementation = _py_package_annotation_consumer_impl,
    attrs = {
        "consume": attr.string(
            doc = "The name of the `py_package_annotation` target to parse from `package`.",
            mandatory = True,
        ),
        "package": attr.label(
            doc = "The python package to parse targets from.",
            aspects = [py_package_annotation_deps_aspect],
            mandatory = True,
        ),
    },
)
