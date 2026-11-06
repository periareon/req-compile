"""Repository rules for downloading and extracting python wheel files"""

load("@package_metadata//purl:purl.bzl", "purl")
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
# repository name, and tooling that reads those tags works with either. The
# targets describing the wheel itself, see `_PACKAGE_METADATA_TEMPLATE`, are
# the exception: they are not the package, they are about it.
_ROOT_BUILD_TEMPLATE = """\
load("@bazel_skylib//rules:copy_file.bzl", "copy_file")
{metadata_loads}load("@rules_venv//python:defs.bzl", "py_binary", "py_library")

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
{package_metadata}"""

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

# The supply chain metadata of the wheel. `REPO.bazel` makes it the
# `package_metadata` of every target of the repository, so tooling that
# collects the metadata of the packages a binary is built from, an SBOM
# generator or a license check, reaches it through whichever hub target led
# there. The purl names the exact distribution the lock pinned, and the license
# is the one the wheel declares in its `METADATA`, when it declares one.
_PACKAGE_METADATA_TEMPLATE = """
package_metadata(
    name = "package_metadata",
    purl = {purl},
    attributes = {attributes},
)
"""

_LICENSE_TEMPLATE = """
license(
    name = "license",
    kind = {kind},
    text = {text},
)
"""

# A license `@package_metadata` has no kind for: a compound SPDX expression,
# an identifier it does not know, or a license text without an identifier.
_LICENSE_KIND_TEMPLATE = """
license_kind(
    name = "license_kind",
    full_name = {full_name},
    identifier = {identifier},
)
"""

_REPO_FILE = """\
# The metadata of the wheel, `//:package_metadata`, is attached to every
# target of the repository.
repo(
    default_package_metadata = ["//:package_metadata"],
)
"""

# The rules a wheel repository declares its metadata with, loaded from this
# module since the repository need not see `@package_metadata`.
_METADATA_RULES = str(Label("//req_compile/private:package_metadata.bzl"))

# The `license_kind`s of `@package_metadata`, one per SPDX license. The
# package is named canonically for the same reason.
_SPDX_BUILD = Label("@package_metadata//licenses/spdx:BUILD")
_SPDX_PACKAGE = str(_SPDX_BUILD)[:-len(":BUILD")]

# Trove classifiers naming one SPDX license. Classifiers predate the
# `License-Expression` field and most do not say which version of a license
# applies (`BSD License`), so only those that do are mapped. `Apache Software
# License` is taken to be 2.0, the only version PyPI has seen in practice.
_LICENSE_CLASSIFIERS = {
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: Boost Software License 1.0 (BSL-1.0)": "BSL-1.0",
    "License :: OSI Approved :: Eclipse Public License 2.0 (EPL-2.0)": "EPL-2.0",
    "License :: OSI Approved :: GNU Affero General Public License v3": "AGPL-3.0-only",
    "License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)": "AGPL-3.0-or-later",
    "License :: OSI Approved :: GNU General Public License v2 (GPLv2)": "GPL-2.0-only",
    "License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)": "GPL-2.0-or-later",
    "License :: OSI Approved :: GNU General Public License v3 (GPLv3)": "GPL-3.0-only",
    "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)": "GPL-3.0-or-later",
    "License :: OSI Approved :: GNU Lesser General Public License v2 (LGPLv2)": "LGPL-2.0-only",
    "License :: OSI Approved :: GNU Lesser General Public License v2 or later (LGPLv2+)": "LGPL-2.0-or-later",
    "License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0-only",
    "License :: OSI Approved :: GNU Lesser General Public License v3 or later (LGPLv3+)": "LGPL-3.0-or-later",
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: MIT No Attribution License (MIT-0)": "MIT-0",
    "License :: OSI Approved :: Mozilla Public License 1.1 (MPL 1.1)": "MPL-1.1",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
    "License :: OSI Approved :: The Unlicense (Unlicense)": "Unlicense",
    "License :: OSI Approved :: zlib/libpng License": "Zlib",
}

# Where setuptools put license files before it implemented PEP 639, which
# puts them under `licenses/` and names each in a `License-File` header.
_LICENSE_FILE_NAMES = ["LICENSE", "LICENSE.txt", "LICENSE.md", "LICENSE.rst", "COPYING"]

def wheel_purl(package, version, file_name = None, url = None, sha256 = None):
    """The purl of a distribution of a Python package.

    Args:
        package (str): The name of the package, as a lock file spells it.
        version (str): The version of the package.
        file_name (str): The file name of the distribution, a wheel or an sdist.
        url (str): Where the distribution was downloaded from, if anywhere.
        sha256 (str): The hex sha256 of the distribution, if known.

    Returns:
        str: A `pkg:pypi/...` purl naming the exact distribution.
    """
    builder = purl.builder().type("pypi").name(package).version(version)
    if file_name:
        builder.add_qualifier("file_name", file_name)
    if url:
        # The fragment, when there is one, repeats the hash.
        builder.add_qualifier("download_url", url.partition("#")[0])
    if sha256:
        builder.add_qualifier("checksum", "sha256:" + sha256)
    return builder.build()

def parse_metadata_license(content):
    """Read the license fields out of the `METADATA` of a wheel.

    Args:
        content (str): The file, RFC 822 headers followed by the description.

    Returns:
        struct: With `expression`, the `License-Expression` of PEP 639; `license`,
            the first line of the free-form `License` field; `files`, the
            `License-File` entries; and `classifiers`, the `License ::` trove
            classifiers. Each is None or empty when the wheel has none.
    """
    expression = None
    license = None
    files = []
    classifiers = []
    for line in content.splitlines():
        if not line.strip():
            # The headers end at the first blank line.
            break
        if line[0] in " \t":
            # A continuation. Only `License` is ever long enough to need one,
            # when setuptools was given a whole license text for it, and its
            # first line is all that is looked at.
            continue
        key, separator, value = line.partition(":")
        if not separator:
            continue
        key = key.strip().lower()
        value = value.strip()
        if key == "license-expression":
            expression = value
        elif key == "license" and value and value != "UNKNOWN":
            # Older setuptools wrote `UNKNOWN` when nothing was declared.
            license = value
        elif key == "license-file":
            files.append(value)
        elif key == "classifier" and value.startswith("License ::"):
            classifiers.append(value)
    return struct(
        expression = expression,
        license = license,
        files = files,
        classifiers = classifiers,
    )

def declared_license(metadata, spdx):
    """The license a wheel declares, from the fields of its `METADATA`.

    PEP 639's `License-Expression` is authoritative. Without it, the free-form
    `License` field is used when it holds exactly an SPDX identifier, and
    failing that a trove classifier naming one license.

    Args:
        metadata (struct): See `parse_metadata_license`.
        spdx (dict): The SPDX identifiers `@package_metadata` has a `license_kind`
            for, keyed by their lowercase form, which is how SPDX compares them.

    Returns:
        struct: With `identifier`, an SPDX identifier or expression, and `kind`,
            the label of its `license_kind` when `@package_metadata` has one, else
            None. None when the wheel declares nothing usable.
    """
    if metadata.expression:
        kind = spdx.get(metadata.expression.lower())
        return struct(
            identifier = kind or metadata.expression,
            kind = "{}:{}".format(_SPDX_PACKAGE, kind) if kind else None,
        )

    candidates = []
    if metadata.license:
        candidates.append(metadata.license)
    for classifier in metadata.classifiers:
        if classifier in _LICENSE_CLASSIFIERS:
            candidates.append(_LICENSE_CLASSIFIERS[classifier])

    for candidate in candidates:
        kind = spdx.get(candidate.lower())
        if kind:
            return struct(
                identifier = kind,
                kind = "{}:{}".format(_SPDX_PACKAGE, kind),
            )
    return None

def _spdx_license_kinds(repository_ctx):
    """The SPDX identifiers `@package_metadata` has a `license_kind` for, keyed by lowercase form."""
    kinds = {}
    for line in repository_ctx.read(_SPDX_BUILD).splitlines():
        line = line.strip()
        if line.startswith("identifier = "):
            identifier = line[len("identifier = "):].rstrip(",").strip("\"")
            kinds[identifier.lower()] = identifier
    return kinds

def _license_text(dist_info_dir, files):
    """The license file of a wheel, as a path in the repository, or None."""
    candidates = []
    for name in files:
        candidates.extend(["licenses/" + name, name])
    if not files:
        candidates.extend(_LICENSE_FILE_NAMES)
    for candidate in candidates:
        if dist_info_dir.get_child(candidate).exists:
            return "site-packages/{}/{}".format(dist_info_dir.basename, candidate)
    return None

def wheel_license(repository_ctx, dist_info_dir, package):
    """The license of an extracted wheel, from its `METADATA`.

    Args:
        repository_ctx (repository_ctx): The rule's context object.
        dist_info_dir (path): The `.dist-info` directory of the wheel.
        package (str): The name of the package, for a license without an identifier.

    Returns:
        struct: With `kind`, the label of a `license_kind` of `@package_metadata`
            or None; `identifier` and `full_name`, the kind to declare when it
            is None; and `text`, the path of the license file or None. None when
            the wheel declares no license at all.
    """
    metadata_file = dist_info_dir.get_child("METADATA")
    metadata = parse_metadata_license(repository_ctx.read(metadata_file) if metadata_file.exists else "")
    text = _license_text(dist_info_dir, metadata.files)

    declared = None
    if metadata.expression or metadata.license or metadata.classifiers:
        declared = declared_license(metadata, _spdx_license_kinds(repository_ctx))

    if declared:
        return struct(
            kind = declared.kind,
            identifier = declared.identifier,
            full_name = declared.identifier,
            text = text,
        )

    if not text:
        return None

    # A license text that no identifier names, which SPDX refers to as
    # `LicenseRef-<id>`. The `License` field is its name when it is one, the
    # field is free text and has held whole license texts.
    full_name = "License of {}".format(package)
    if metadata.license and len(metadata.license) <= 80:
        full_name = metadata.license
    return struct(
        kind = None,
        identifier = "LicenseRef-{}".format(sanitize_package_name(package).replace("_", "-")),
        full_name = full_name,
        text = text,
    )

def render_package_metadata(distribution, license):
    """Render the metadata targets of a wheel repository.

    Args:
        distribution (str): The purl of the distribution, see `wheel_purl`.
        license (struct): The license of the wheel, see `wheel_license`, or None.

    Returns:
        struct: With `loads`, the `load` statement the targets need, and
            `content`, the targets, both Starlark source.
    """
    symbols = ["package_metadata"]
    content = _PACKAGE_METADATA_TEMPLATE.format(
        purl = json.encode(distribution),
        attributes = json.encode([":license"] if license else []),
    )
    if license:
        symbols.insert(0, "license")
        kind = license.kind
        if not kind:
            kind = ":license_kind"
            symbols.insert(1, "license_kind")
            content += _LICENSE_KIND_TEMPLATE.format(
                full_name = json.encode(license.full_name),
                identifier = json.encode(license.identifier),
            )
        content += _LICENSE_TEMPLATE.format(
            kind = json.encode(kind),
            text = json.encode(license.text) if license.text else "None",
        )
    return struct(
        loads = "load({}, {})\n".format(
            json.encode(_METADATA_RULES),
            ", ".join([json.encode(symbol) for symbol in symbols]),
        ),
        content = content,
    )

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
    repository_ctx.file("REPO.bazel", _REPO_FILE)

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

    # The distribution the lock pinned, which for an sdist is not the wheel
    # built from it.
    artifact_name = whl_name

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

    metadata = render_package_metadata(
        distribution = wheel_purl(
            repository_ctx.attr.package,
            repository_ctx.attr.version,
            file_name = artifact_name,
            url = repository_ctx.attr.urls[0] if repository_ctx.attr.urls else None,
            sha256 = whl_sha256,
        ),
        license = wheel_license(repository_ctx, dist_info_dir, repository_ctx.attr.package),
    )

    root_content = [_ROOT_BUILD_TEMPLATE.format(
        name = package_name,
        tags = tags,
        metadata_loads = metadata.loads,
        package_metadata = metadata.content,
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

    # A download without a checksum is pinned by the one Bazel computed. Bazel 7
    # reads a returned dict as the attributes that would make the repository
    # reproducible and has no `repo_metadata` to say anything else.
    attrs_for_reproducibility = {
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
    if not hasattr(repository_ctx, "repo_metadata"):
        return attrs_for_reproducibility
    if not repository_ctx.attr.sha256:
        return repository_ctx.repo_metadata(
            attrs_for_reproducibility = attrs_for_reproducibility,
        )

    # A wheel pinned by its checksum is a function of the attributes and the
    # files they name, so Bazel may share the repository across workspaces
    # through the repo contents cache. A wheel built from an sdist is not: the
    # build runs the interpreter against whatever the host provides.
    return repository_ctx.repo_metadata(
        reproducible = artifact_name.endswith(".whl"),
    )

whl_repository = repository_rule(
    doc = """\
A repository rule for extracting a python [wheel](https://peps.python.org/pep-0491/) and defining a `py_library`.

This repository is expected to be generated by [py_requirements_repository](#py_requirements_repository).

The repository contains the wheel (`//:whl`), a `py_library` named after the package (`//:requests`) holding its
files but none of its dependencies, and a target per hub using the wheel (`//:pip_deps.requests`) holding its files
with the dependencies that hub resolved for the package, or aliasing the package when the hub resolved none. The
console scripts of the wheel are a `py_binary` per hub (`//:pip_deps.entry_point_<script>`). This allows a single
repository to be shared by every hub that pins the same wheel, even when they resolved its dependencies differently.

Every target of the repository carries the `package_metadata` of the wheel (`//:package_metadata`), from the
`@package_metadata` module: a `pkg:pypi` purl naming the distribution the lock pinned, with its file name, download
URL and sha256 as qualifiers, and the license the wheel declares in its `METADATA` (`//:license`), when it declares
one. The hub's aliases resolve to these targets, so tooling collecting the metadata of a binary's dependencies, such
as an SBOM generator, sees the wheel behind each requirement.
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
