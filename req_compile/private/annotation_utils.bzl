"""Utilities for applying annotations to Bazel python packages.

Split this from annotation.bzl since it loads CcInfo and this causes
a circular load() with rules_cc in WORKSPACE.bazel.
"""

# The owner recorded for annotations declared by the root module.
ROOT_MODULE = "<root>"

def record_annotation(annotations, owners, package, data, module, is_root):
    """Record the annotation a module declares for a package.

    Annotations are collected from every module. The root module decides any
    disagreement, other modules must agree with each other. A module repeating
    exactly what was already recorded never changes who decided it.

    Args:
        annotations (dict): Package name to the serialized annotation recorded so far.
        owners (dict): Package name to the module whose annotation is recorded.
        package (str): The annotated package.
        data (str): The serialized annotation.
        module (str): The name of the module declaring it.
        is_root (bool): Whether that module is the root module.
    """
    owner = ROOT_MODULE if is_root else module
    if package not in annotations:
        annotations[package] = data
        owners[package] = owner
        return

    if annotations[package] == data:
        # Identical, nothing to decide. The root still claims it so that a later
        # disagreement from a dependency cannot override it.
        if is_root:
            owners[package] = owner
        return

    if is_root:
        annotations[package] = data
        owners[package] = owner
    elif owners[package] != ROOT_MODULE:
        fail("Module `{}` and module `{}` annotate the python package `{}` differently. Annotate it from the root module to decide.".format(
            owners[package],
            module,
            package,
        ))

def deserialize_package_annotation(content):
    """Deserialize json encoded `py_package_annotation` data.

    Args:
        content (str): A json serialized string.

    Returns:
        struct: `py_package_annotation` data.
    """
    data = json.decode(content)

    # TODO: There should be no need for the double deserialization
    if data:
        data = json.decode(data)
    else:
        data = {}

    additive_build_file = None
    if data.get("additive_build_file", None):
        additive_build_file = Label(data["additive_build_file"])

    additive_content = ""
    if data.get("additive_build_file_content", None):
        additive_content += data["additive_build_file_content"]
    if data.get("additive_build_content", None):
        additive_content += data["additive_build_content"]

    return struct(
        additive_build_file_content = additive_content or None,
        additive_build_file = additive_build_file,
        copy_srcs = data.get("copy_srcs", {}),
        copy_files = data.get("copy_files", {}),
        copy_executables = data.get("copy_executables", {}),
        data = data.get("data", []),
        data_exclude_glob = data.get("data_exclude_glob", []),
        srcs_exclude_glob = data.get("srcs_exclude_glob", []),
        deps = data.get("deps", []),
        deps_excludes = data.get("deps_excludes", []),
        patches = data.get("patches", []),
    )
