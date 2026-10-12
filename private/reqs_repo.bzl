"""Repository rules for loading platform specific python requirements"""

load(":lockfile.bzl", _parse_lock_header = "parse_lock_header", _parse_lockfile = "parse_lockfile")
load(":utils.bzl", "sanitize_package_name", "whl_repo_name")
load(":whl_repo.bzl", "whl_repository")

# Re-exported for compatibility.
parse_lockfile = _parse_lockfile
parse_lock_header = _parse_lock_header

def _canonical(label):
    """Canonicalize a label visible to `rules_req_compile` for use in generated files."""
    return str(Label(label))

# Bazel CPU constraints for the architectures found in wheel platform tags.
_CPU_CONSTRAINTS = {
    "aarch64": _canonical("@platforms//cpu:aarch64"),
    "amd64": _canonical("@platforms//cpu:x86_64"),
    "arm64": _canonical("@platforms//cpu:aarch64"),
    "armv7l": _canonical("@platforms//cpu:armv7"),
    "i686": _canonical("@platforms//cpu:x86_32"),
    "ppc64le": _canonical("@platforms//cpu:ppc64le"),
    "s390x": _canonical("@platforms//cpu:s390x"),
    "x86_64": _canonical("@platforms//cpu:x86_64"),
}

_OS_CONSTRAINTS = {
    "linux": _canonical("@platforms//os:linux"),
    "macos": _canonical("@platforms//os:macos"),
    "windows": _canonical("@platforms//os:windows"),
}

_WINDOWS_TAGS = {
    "win32": "i686",
    "win_amd64": "x86_64",
    "win_arm64": "aarch64",
}

def platform_constraint_values(tag):
    """The Bazel constraints matching a wheel platform tag.

    `req-compile` records the platform a lock was compiled for in the header of
    the lock file as the wheel platform tag that was requested, e.g.
    `manylinux_2_28_x86_64`, `macosx_11_0_arm64` or `win_amd64`.

    Args:
        tag (str): The wheel platform tag.

    Returns:
        list[str]: The `constraint_value` labels, or None if the tag is not understood.
    """
    if not tag:
        return None
    tag = tag.lower().replace("-", "_")

    os_name = None
    arch = None
    if tag.startswith("manylinux_"):
        # manylinux_<major>_<minor>_<arch>
        os_name = "linux"
        parts = tag.split("_", 3)
        arch = parts[3] if len(parts) == 4 else None
    elif tag.startswith("manylinux"):
        # manylinux1_<arch>, manylinux2010_<arch>, manylinux2014_<arch>
        os_name = "linux"
        _, _, arch = tag.partition("_")
    elif tag.startswith("linux_"):
        os_name = "linux"
        arch = tag[len("linux_"):]
    elif tag.startswith("macosx_"):
        os_name = "macos"
        parts = tag.split("_", 3)
        arch = parts[3] if len(parts) == 4 else None
        if arch == "universal2":
            # Fat wheels run on either architecture.
            return [_OS_CONSTRAINTS[os_name]]
    elif tag in _WINDOWS_TAGS:
        os_name = "windows"
        arch = _WINDOWS_TAGS[tag]

    if not os_name or arch not in _CPU_CONSTRAINTS:
        return None
    return [_OS_CONSTRAINTS[os_name], _CPU_CONSTRAINTS[arch]]

_INCOMPATIBLE = _canonical("@platforms//:incompatible")

def lock_spec(
        file,
        id = None,
        constraint_values = [],
        flag_values = {},
        config_setting = None,
        default = False):
    """Describe a lock file belonging to a hub.

    Args:
        file (Label): The lock file.
        id (str): A name for the lock, unique within its hub. Defaults to the
            platform recorded in the header of the lock file, or failing that to
            the file name.
        constraint_values (list[Label]): `constraint_value`s that must be satisfied
            for the lock to be selected.
        flag_values (dict[Label, str]): Flag values that must be set for the lock
            to be selected.
        config_setting (Label): An existing `config_setting` selecting the lock.
            Mutually exclusive with `constraint_values` and `flag_values`.
        default (bool): Whether this lock is used when no other lock matches.

    Returns:
        struct: The lock specification.
    """
    return struct(
        file = file,
        id = id,
        constraint_values = list(constraint_values),
        flag_values = dict(flag_values),
        config_setting = config_setting,
        default = default,
    )

def hub_spec(
        name,
        locks,
        module = None,
        interpreter = None,
        package_aliases = {},
        legacy_root_pkg_aliases = False,
        alias_of = None):
    """Describe a hub repository to generate.

    Args:
        name (str): The name of the hub repository.
        locks (list[struct]): The `lock_spec`s of the hub.
        module (str): The name of the Bazel module defining the hub.
        interpreter (Label): The interpreter used to build source distributions.
        package_aliases (dict[Label, str]): `py_library` targets replacing packages.
        legacy_root_pkg_aliases (bool): Whether to alias packages at the root of the hub.
        alias_of (str): The name of another hub this hub should defer to.

    Returns:
        struct: The hub specification.
    """
    return struct(
        name = name,
        locks = list(locks),
        module = module,
        interpreter = interpreter,
        package_aliases = dict(package_aliases),
        legacy_root_pkg_aliases = legacy_root_pkg_aliases,
        alias_of = alias_of,
    )

def _sanitize_id(text):
    return "".join([
        char if char.isalnum() or char in "_-." else "_"
        for char in text.elems()
    ]).strip("_-.")

def _derive_lock_id(spec, header):
    if spec.id:
        return _sanitize_id(spec.id)

    # Only trust platforms req-compile knows about. Older lock files recorded the
    # operating system of the compiling machine here, which does not identify a lock.
    if platform_constraint_values(header.platform):
        return _sanitize_id(header.platform)

    # Fall back to the historical behavior of naming the lock after its file.
    name, _, _ = str(spec.file).rpartition(":")[2].rpartition(".")
    name = name.replace("requirements", "").replace(".", "_").replace("-", "_").strip(" -_.")
    return _sanitize_id(name) or "default"

def _lock_config(hub_name, spec, header, multiple):
    """Determine how a hub selects a lock.

    Returns:
        dict: With `constraint_values`, `flag_values` and `config_setting` entries,
            or None if the lock needs no selection.
    """
    if spec.config_setting and (spec.constraint_values or spec.flag_values):
        fail("Lock `{}` of hub `{}` sets `config_setting` together with `constraint_values` or `flag_values`. Use one or the other.".format(
            spec.file,
            hub_name,
        ))

    if spec.config_setting:
        return {
            "config_setting": str(spec.config_setting),
            "constraint_values": [],
            "flag_values": {},
        }

    if spec.constraint_values or spec.flag_values:
        return {
            "config_setting": None,
            "constraint_values": [str(value) for value in spec.constraint_values],
            "flag_values": {str(flag): value for flag, value in spec.flag_values.items()},
        }

    if not multiple:
        return None

    constraint_values = platform_constraint_values(header.platform)
    if constraint_values:
        return {
            "config_setting": None,
            "constraint_values": constraint_values,
            "flag_values": {},
        }

    fail((
        "Lock `{}` of hub `{}` does not say which platform it applies to. Either map it to a config " +
        "setting with `config_settings`, or compile it with the `platform` attribute of `py_reqs_compiler` " +
        "so the platform is recorded in the header of the file. The header says: {}"
    ).format(spec.file, hub_name, header.platform or "nothing"))

def _identity(data):
    """Something identifying the exact distribution a lock entry resolved to."""
    if data["sha256"]:
        return data["sha256"]
    if data["url"]:
        return data["url"]
    if data["whl"]:
        return data["whl"]
    return "{}=={}".format(data["package"], data["version"])

def _check_same(name, existing, attrs, hub_name):
    for key in ("package", "version", "sha256", "urls", "whl", "annotations"):
        if existing[key] != attrs[key]:
            fail("Hub `{}` resolved `{}=={}` to a distribution that conflicts with hub(s) {} on `{}` ({} != {}). This is a bug in req-compile, please report it.".format(
                hub_name,
                attrs["package"],
                attrs["version"],
                sorted(existing["hubs"].keys()),
                key,
                attrs[key],
                existing[key],
            ))
    if existing["interpreter"] and attrs["interpreter"] and existing["interpreter"] != attrs["interpreter"]:
        fail("The source distribution `{}=={}` is used by hub `{}` and hub(s) {} with different interpreters ({} != {}). Repository `{}` can only be built with one.".format(
            attrs["package"],
            attrs["version"],
            hub_name,
            sorted(existing["hubs"].keys()),
            attrs["interpreter"],
            existing["interpreter"],
            name,
        ))

def plan_hubs(ctx, hubs, annotations):
    """Plan the repositories needed for a set of hubs.

    Every distinct wheel is downloaded into a single `whl_repository` which is
    shared by every hub that pins it.

    Args:
        ctx (module_ctx or repository_ctx): A context able to read files.
        hubs (dict[str, struct]): `hub_spec`s keyed by hub name.
        annotations (dict[str, str]): Serialized `py_package_annotation`s keyed by package name.

    Returns:
        struct: With `wheel_repos`, a mapping of repository name to `whl_repository`
            attributes, and `hubs`, a mapping of hub name to the data needed to
            generate the hub.
    """
    wheel_repos = {}
    planned = {}

    # Hubs deferring to another hub are planned last, once the hub they
    # defer to is known.
    ordered = sorted(hubs.keys(), key = lambda name: (1 if hubs[name].alias_of else 0, name))

    for hub_name in ordered:
        hub = hubs[hub_name]
        if not hub.locks:
            fail("Hub `{}` has no lock files. Add `lock` tags for it or set `requirements_lock`.".format(hub_name))

        # Empty lock files are skipped so that a hub can be declared before its
        # locks are compiled for the first time.
        contents = [(spec, ctx.read(ctx.path(spec.file))) for spec in hub.locks]
        contents = [(spec, content) for spec, content in contents if content.strip()]

        multiple = len(contents) > 1
        locks = []
        packages = {}
        default_lock = None
        for spec, content in contents:
            header = parse_lock_header(content)
            lock_id = _derive_lock_id(spec, header)
            if lock_id in [lock["id"] for lock in locks]:
                fail("Hub `{}` has more than one lock with the id `{}`. Set a unique `id` on each lock.".format(
                    hub_name,
                    lock_id,
                ))

            if spec.default:
                if default_lock:
                    fail("Hub `{}` has more than one default lock (`{}` and `{}`).".format(
                        hub_name,
                        default_lock,
                        lock_id,
                    ))
                default_lock = lock_id

            config = _lock_config(hub_name, spec, header, multiple)
            if config and not config["config_setting"]:
                # Two locks deriving the same platform from their headers would make
                # every select of the hub ambiguous. Catch it here instead.
                for other in locks:
                    if other["config"] and other["config"]["constraint_values"] == config["constraint_values"]:
                        fail((
                            "Locks `{}` and `{}` of hub `{}` are both for {}. Map every lock of the hub to " +
                            "your own config settings with `config_settings` to say when each applies."
                        ).format(other["file"], spec.file, hub_name, header.platform))
            locks.append({
                "config": config,
                "default": spec.default,
                "file": str(spec.file),
                "id": lock_id,
            })

            lock_packages = parse_lockfile(
                content = content,
                annotations = annotations,
                lockfile = spec.file,
            )

            config_setting = "@{}//:{}".format(hub.alias_of or hub_name, lock_id) if config else None

            for pkg, data in lock_packages.items():
                annotations_json = json.encode(data["annotations"])
                repo_name = whl_repo_name(
                    data["package"],
                    data["version"],
                    _identity(data),
                    annotations_json if data["annotations"] else None,
                )
                packages.setdefault(pkg, {})[lock_id] = {
                    "repo": repo_name,
                    "version": data["version"],
                }

                if hub.alias_of:
                    # The hub this one defers to provides the repositories.
                    continue

                attrs = {
                    "annotations": annotations_json,
                    "hubs": {},
                    "interpreter": hub.interpreter,
                    "package": data["package"],
                    "sha256": data["sha256"],
                    "urls": [data["url"]] if data["url"] else None,
                    "version": data["version"],
                    "whl": data["whl"],
                }
                if repo_name in wheel_repos:
                    _check_same(repo_name, wheel_repos[repo_name], attrs, hub_name)
                    if not wheel_repos[repo_name]["interpreter"]:
                        wheel_repos[repo_name]["interpreter"] = hub.interpreter
                else:
                    wheel_repos[repo_name] = attrs

                wheel_repos[repo_name]["hubs"].setdefault(hub_name, {})[lock_id] = {
                    "config_setting": config_setting,
                    "deps": data["deps"],
                }

        if hub.alias_of:
            parent = planned.get(hub.alias_of)
            if not parent:
                fail("Hub `{}` defers to hub `{}` which does not exist.".format(hub_name, hub.alias_of))

            # Use the parent's resolution for everything. Packages the parent does not
            # provide keep pointing at it, so they fail only if something uses them.
            locks = parent.locks
            default_lock = parent.default_lock
            packages = {pkg: parent.packages.get(pkg, data) for pkg, data in packages.items()}

        planned[hub_name] = struct(
            name = hub_name,
            alias_of = hub.alias_of,
            default_lock = default_lock,
            legacy_root_pkg_aliases = hub.legacy_root_pkg_aliases,
            locks = locks,
            package_aliases = hub.package_aliases,
            packages = packages,
        )

    return struct(
        hubs = planned,
        wheel_repos = wheel_repos,
    )

def create_hub_repos(plan):
    """Instantiate the repositories of a plan produced by `plan_hubs`.

    Args:
        plan (struct): See `plan_hubs`.
    """
    for name, attrs in plan.wheel_repos.items():
        whl_repository(
            name = name,
            annotations = attrs["annotations"],
            hubs = json.encode(attrs["hubs"]),
            interpreter = attrs["interpreter"],
            package = attrs["package"],
            sha256 = attrs["sha256"],
            urls = attrs["urls"],
            version = attrs["version"],
            whl = attrs["whl"],
        )

    for name, hub in plan.hubs.items():
        py_requirements_repository(
            name = name,
            hub_name = name,
            alias_of = hub.alias_of or "",
            default_lock = hub.default_lock or "",
            legacy_root_pkg_aliases = hub.legacy_root_pkg_aliases,
            locks = json.encode(hub.locks),
            package_aliases = hub.package_aliases,
            packages = json.encode(hub.packages),
        )

_DEFS_BZL_TEMPLATE = """\
\"\"\"Python requirements of the `{hub}` hub.\"\"\"

load("@rules_req_compile//private:utils.bzl", "sanitize_package_name")

# The hub whose packages are defined in the shared wheel repositories.
_WHEEL_HUB = "{wheel_hub}"

# Mapping of package name to the version and repository resolved by each lock.
_PACKAGES = {packages}

# The ids of the locks of the hub, in order.
_LOCKS = {locks}

# The lock used when no other lock matches, if any.
_DEFAULT_LOCK = {default_lock}

def _select(values, default = None):
    \"\"\"Select a value per lock.

    Args:
        values (dict): Mapping of lock id to value. Locks may be omitted when
            the value does not exist for them.
        default: The value when no lock matches. Defaults to the value of the
            default lock, if one is configured.

    Returns:
        The value itself when the hub has a single lock, otherwise a `select`.
    \"\"\"
    if len(_LOCKS) == 1 and _LOCKS[0] in values:
        return values[_LOCKS[0]]

    branches = {{}}
    for lock_id in _LOCKS:
        if lock_id in values:
            branches[Label("//:" + lock_id)] = values[lock_id]
    if default != None:
        branches["//conditions:default"] = default
    elif _DEFAULT_LOCK and _DEFAULT_LOCK in values:
        branches["//conditions:default"] = values[_DEFAULT_LOCK]
    return select(branches)

def _package_data(name):
    pkg = sanitize_package_name(name)
    if pkg not in _PACKAGES:
        fail("`{{}}` is not a package of the `{hub}` hub. Available: {{}}".format(
            name,
            ", ".join(sorted(_PACKAGES)),
        ))
    return pkg, _PACKAGES[pkg]

def whl_repo_name(package):
    \"\"\"The name of the repository holding the wheel of a package.\"\"\"
    _, data = _package_data(package)
    repos = sorted(depset([lock["repo"] for lock in data.values()]).to_list())
    if len(repos) != 1:
        fail("The wheel repository of `{{}}` depends on the platform: {{}}".format(package, repos))
    return repos[0]

def get_version(pkg):
    \"\"\"The version a package was pinned to.\"\"\"
    _, data = _package_data(pkg)
    versions = {{lock_id: lock["version"] for lock_id, lock in data.items()}}
    if len(depset(versions.values()).to_list()) == 1:
        return versions.values()[0]
    return _select(versions)

def requirement(name):
    \"\"\"The `py_library` of a package.\"\"\"
    pkg = sanitize_package_name(name)
    return Label("//{{}}:{{}}".format(pkg, pkg))

def requirements(names):
    return [requirement(name) for name in names]

def requirement_wheel(name):
    \"\"\"The wheel file of a package.\"\"\"
    return Label("//{{}}:whl".format(sanitize_package_name(name)))

def requirements_wheels(names):
    return [requirement_wheel(name) for name in names]

def entry_point(pkg, script = None, output_list = False):
    \"\"\"The `py_binary` of a console script of a package.

    Args:
        pkg (str): The package providing the script.
        script (str): The name of the script. Defaults to the package name.
        output_list (bool): Whether to return a list of labels instead of a label.

    Returns:
        The label of the `py_binary`, or a `select` of labels when the
        hub has more than one lock.
    \"\"\"
    if not script:
        script = pkg
    _, data = _package_data(pkg)
    targets = {{
        lock_id: Label("@{{}}//{{}}:entry_point_{{}}".format(lock["repo"], _WHEEL_HUB, script))
        for lock_id, lock in data.items()
    }}
    if output_list:
        return _select({{lock_id: [target] for lock_id, target in targets.items()}})
    return _select(targets)

def _all(fn):
    if not _LOCKS:
        return []
    per_lock = {{
        lock_id: [fn(pkg) for pkg in sorted(_PACKAGES) if lock_id in _PACKAGES[pkg]]
        for lock_id in _LOCKS
    }}
    if len(depset([json.encode([str(label) for label in labels]) for labels in per_lock.values()]).to_list()) == 1:
        return per_lock.values()[0]
    return _select(per_lock)

all_requirements = _all(requirement)

all_requirements_wheels = _all(requirement_wheel)

def repositories():
    \"\"\"Kept for compatibility, repositories are created by the module extension.\"\"\"
    pass
"""

_RULES_PYTHON_COMPAT = """\
\"\"\"A compatibility file with rules_python\"\"\"

load("@rules_req_compile//private:utils.bzl", "sanitize_package_name")
load(
    ":defs.bzl",
    "repositories",
    _all_requirements = "all_requirements",
    _entry_point = "entry_point",
    _get_version = "get_version",
    _requirement = "requirement",
)

all_requirements = _all_requirements
entry_point = _entry_point
get_version = _get_version
install_deps = repositories

def requirement(name):
    \"\"\"rules_python compatibility macro\"\"\"
    pkg_name = sanitize_package_name(name)
    return Label("@{repository_name}" + "//" + ("" if {legacy_root_pkg_aliases} else pkg_name) + ":" + pkg_name)
"""

_BUILD_FILE_TEMPLATE = """\
package(default_visibility = ["//visibility:public"])

exports_files(["defs.bzl", "requirements.bzl"])
{config_settings}
{legacy_aliases}
"""

_CONFIG_SETTING_TEMPLATE = """\
config_setting(
    name = "{name}",
    constraint_values = {constraint_values},
    flag_values = {flag_values},
)
"""

_CONFIG_SETTING_ALIAS_TEMPLATE = """\
alias(
    name = "{name}",
    actual = "{actual}",
)
"""

_WHEELS_BUILD_FILE_TEMPLATE = """\
package(default_visibility = ["//visibility:public"])

filegroup(
    name = "all_wheels",
    srcs = {all_wheels_srcs},
    tags = ["manual"],
)
"""

_PACKAGE_BUILD_FILE_TEMPLATE = """\
load("@rules_python//python:defs.bzl", "py_library")

package(default_visibility = ["//visibility:public"])

alias(
    name = "{pkg}",
    actual = {actual},
    tags = ["manual"],
)

alias(
    name = "whl",
    actual = {whl},
    tags = ["manual"],
)

# The package is not part of every lock of the hub. Targets depending on it
# are incompatible with the platforms it is missing from.
py_library(
    name = "{pkg}.unavailable",
    tags = ["manual"],
    target_compatible_with = ["{incompatible}"],
)

filegroup(
    name = "whl.unavailable",
    tags = ["manual"],
    target_compatible_with = ["{incompatible}"],
)
"""

_ALIAS_TEMPLATE = """\
alias(
    name = "{name}",
    actual = "{target}",
    tags = ["manual"],
)
"""

_PACKAGE_ALIAS_BUILD_FILE_TEMPLATE = """\
package(default_visibility = ["//visibility:public"])

""" + _ALIAS_TEMPLATE

_LEGACY_ALIAS_TEMPLATE = """\
alias(
    name = "{pkg}",
    actual = "//{pkg}",
    tags = ["manual"],
)

alias(
    name = "{pkg}_whl",
    actual = "//{pkg}:whl",
    tags = ["manual"],
)
"""

_LEGACY_ALL_WHEELS_TEMPLATE = """\
alias(
    name = "all_wheels",
    actual = "//all_wheels",
    tags = ["manual"],
)
"""

def _render_select(lock_ids, values, default):
    """Render a `select` over the locks of a hub for use in a BUILD file.

    Args:
        lock_ids (list[str]): All lock ids of the hub, in order.
        values (dict[str, str]): Mapping of lock id to a rendered value.
        default (str): The rendered value when no lock matches, or None.

    Returns:
        str: Starlark source.
    """
    if not lock_ids:
        return default if default != None else "[]"
    if len(lock_ids) == 1 and lock_ids[0] in values and default == None:
        return values[lock_ids[0]]

    lines = ["select({"]
    for lock_id in lock_ids:
        if lock_id in values:
            lines.append("        \"//:{}\": {},".format(lock_id, values[lock_id]))
    if default != None:
        lines.append("        \"//conditions:default\": {},".format(default))
    lines.append("    })")
    return "\n".join(lines)

def _py_requirements_repository_impl(repository_ctx):
    hub_name = repository_ctx.attr.hub_name or repository_ctx.attr.name
    locks = json.decode(repository_ctx.attr.locks)
    packages = json.decode(repository_ctx.attr.packages)
    alias_of = repository_ctx.attr.alias_of
    default_lock = repository_ctx.attr.default_lock or None
    wheel_hub = alias_of or hub_name
    lock_ids = [lock["id"] for lock in locks]

    alias_dict = {}
    for target, package_name in repository_ctx.attr.package_aliases.items():
        alias_dict[sanitize_package_name(package_name)] = str(target)

    # Config settings selecting each lock.
    config_settings = []
    for lock in locks:
        config = lock["config"]
        if not config:
            continue
        if alias_of:
            config_settings.append(_CONFIG_SETTING_ALIAS_TEMPLATE.format(
                name = lock["id"],
                actual = "@{}//:{}".format(alias_of, lock["id"]),
            ))
        elif config["config_setting"]:
            config_settings.append(_CONFIG_SETTING_ALIAS_TEMPLATE.format(
                name = lock["id"],
                actual = config["config_setting"],
            ))
        else:
            config_settings.append(_CONFIG_SETTING_TEMPLATE.format(
                name = lock["id"],
                constraint_values = json.encode_indent(config["constraint_values"], indent = " " * 4),
                flag_values = json.encode_indent(config["flag_values"], indent = " " * 4),
            ))

    unique_packages = sorted(depset(packages.keys() + alias_dict.keys()).to_list())
    legacy_alias_lines = [_LEGACY_ALL_WHEELS_TEMPLATE]

    for pkg in unique_packages:
        if pkg in alias_dict:
            contents = _PACKAGE_ALIAS_BUILD_FILE_TEMPLATE.format(name = pkg, target = alias_dict[pkg])
            legacy_alias_lines.append(_ALIAS_TEMPLATE.format(name = pkg, target = alias_dict[pkg]))
        elif alias_of:
            contents = _PACKAGE_ALIAS_BUILD_FILE_TEMPLATE.format(
                name = pkg,
                target = "@{}//{}".format(alias_of, pkg),
            ) + "\n" + _ALIAS_TEMPLATE.format(
                name = "whl",
                target = "@{}//{}:whl".format(alias_of, pkg),
            )
        else:
            data = packages[pkg]
            heterogeneous = len(data) != len(lock_ids)
            if default_lock and default_lock in data:
                default_library = "\"@{}//{}:pkg\"".format(data[default_lock]["repo"], wheel_hub)
                default_whl = "\"@{}//:whl\"".format(data[default_lock]["repo"])
            elif heterogeneous:
                default_library = "\":{}.unavailable\"".format(pkg)
                default_whl = "\":whl.unavailable\""
            else:
                default_library = None
                default_whl = None

            contents = _PACKAGE_BUILD_FILE_TEMPLATE.format(
                pkg = pkg,
                actual = _render_select(
                    lock_ids,
                    {lock_id: "\"@{}//{}:pkg\"".format(lock["repo"], wheel_hub) for lock_id, lock in data.items()},
                    default_library,
                ),
                whl = _render_select(
                    lock_ids,
                    {lock_id: "\"@{}//:whl\"".format(lock["repo"]) for lock_id, lock in data.items()},
                    default_whl,
                ),
                incompatible = _INCOMPATIBLE,
            )
        repository_ctx.file(
            "{}/BUILD.bazel".format(pkg),
            contents,
        )

    # Create the wheels subpackage with all_wheels filegroup
    wheels_per_lock = {
        lock_id: json.encode_indent([
            "//{}:whl".format(pkg)
            for pkg in unique_packages
            if pkg not in alias_dict and (alias_of or lock_id in packages[pkg])
        ], indent = " " * 8)
        for lock_id in lock_ids
    }
    repository_ctx.file(
        "all_wheels/BUILD.bazel",
        _WHEELS_BUILD_FILE_TEMPLATE.format(
            all_wheels_srcs = _render_select(lock_ids, wheels_per_lock, None),
        ),
    )

    # Generate legacy aliases in root BUILD if requested
    legacy_aliases = ""
    if repository_ctx.attr.legacy_root_pkg_aliases:
        for pkg in unique_packages:
            if pkg not in alias_dict:
                legacy_alias_lines.append(_LEGACY_ALIAS_TEMPLATE.format(
                    pkg = pkg,
                ))
        legacy_aliases = "\n" + "\n".join(legacy_alias_lines)

    repository_ctx.file("BUILD.bazel", _BUILD_FILE_TEMPLATE.format(
        config_settings = "\n" + "\n".join(config_settings) if config_settings else "",
        legacy_aliases = legacy_aliases,
    ))

    repository_ctx.file("defs.bzl", _DEFS_BZL_TEMPLATE.format(
        hub = hub_name,
        wheel_hub = wheel_hub,
        packages = json.encode_indent(packages, indent = " " * 4),
        locks = json.encode(lock_ids),
        default_lock = json.encode(default_lock) if default_lock else "None",
    ))
    repository_ctx.file("WORKSPACE.bazel", """workspace(name = "{}")""".format(
        repository_ctx.name,
    ))
    repository_ctx.file("requirements.bzl", _RULES_PYTHON_COMPAT.format(
        repository_name = hub_name,
        legacy_root_pkg_aliases = "True" if repository_ctx.attr.legacy_root_pkg_aliases else "False",
    ))

py_requirements_repository = repository_rule(
    doc = """\
The hub repository of a set of Python requirements.

This repository is created by the `requirements` module extension, which also creates
a [whl_repository](#whl_repository) for every distinct wheel pinned by any hub. Hubs
sharing a pinned wheel share its repository.

The hub provides a package per Python project it contains, with the `py_library` of the
project as its default target and the wheel file as `:whl`, as well as a generated
`defs.bzl` file.

```python
load("@py_requirements//:defs.bzl", "requirement")

py_library(
    name = "bar",
    ...
    deps = [
        "//my/other:dep",
        requirement("requests"),
        requirement("numpy"),
    ],
)
```

`requirement("requests")` is the same target as `@py_requirements//requests`.

When a hub has more than one lock, each package selects the wheel of the lock matching the
configuration. A package missing from some of the locks is incompatible with the platforms
of those locks, so targets depending on it are skipped there instead of failing to analyze.

In addition to the `requirement` macro, which is used to access the generated `py_library`
target generated from a package's wheel, the generated `defs.bzl` file contains
functionality for exposing [entry points][whl_ep] as `py_binary` targets as well.

[whl_ep]: https://packaging.python.org/specifications/entry-points/

```python
load("@py_requirements//:defs.bzl", "entry_point")

alias(
    name = "pip-compile",
    actual = entry_point(
        pkg = "pip-tools",
        script = "pip-compile",
    ),
)
```

Note that for packages whose name and script are the same, only the name of the package
is needed when calling the `entry_point` macro.

```python
load("@py_requirements//:defs.bzl", "entry_point")

alias(
    name = "flake8",
    actual = entry_point("flake8"),
)
```

A very important detail for generating python dependencies is sdist (source distribution)
dependencies are assumed to be incapable of yielding deterministic outputs. Therefore, any
case where a sdist (source distribution) is found in a lock file, the dependencies should
not be considered byte-for-byte reproducible. It is highly recommended solution files contain
all wheels so the generated repositories are byte-for-byte consistent. Failure to use binary-only
dependencies will result in unexpected cache invalidation as well as inconsistent or broken
cross-platform behavior.
""",
    implementation = _py_requirements_repository_impl,
    attrs = {
        "alias_of": attr.string(
            doc = "The name of a hub every package of this hub is an alias of. Used to override the hubs of dependent modules.",
        ),
        "default_lock": attr.string(
            doc = "The id of the lock used when no lock of the hub matches the configuration.",
        ),
        "hub_name": attr.string(
            doc = "Name of the hub repository to generate. Do not use directly.",
        ),
        "legacy_root_pkg_aliases": attr.bool(
            doc = (
                "If True, creates aliases in the root BUILD.bazel file pointing to the " +
                "package targets in their subpackages. This provides backward compatibility " +
                "for code that references packages at the root (e.g., `@repo//:package_name`)."
            ),
            default = False,
        ),
        "locks": attr.string(
            doc = "A json encoded list of the locks of the hub and how each is selected.",
            mandatory = True,
        ),
        "package_aliases": attr.label_keyed_string_dict(
            doc = "Packages to override with a local `py_library`.",
        ),
        "packages": attr.string(
            doc = "A json encoded mapping of package names to the version and `whl_repository` resolved by each lock.",
            mandatory = True,
        ),
    },
)
