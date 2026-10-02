"""Utilities for applying annotations to Bazel python packages.

Split this from annotation.bzl since it loads CcInfo and this causes
a circular load() with rules_cc in WORKSPACE.bazel.
"""

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
