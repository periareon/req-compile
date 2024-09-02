"""Repository rules for loading platform specific python requirements"""

load(":utils.bzl", "sanitize_package_name")

_CONSTRAINTS_BZL_TEMPLATE = """\
\"\"\"Python constraints\"\"\"

load("@bazel_tools//tools/build_defs/repo:utils.bzl", "maybe")
load("@rules_req_compile//private:sdist_repo.bzl", "sdist_repository")
load("@rules_req_compile//private:utils.bzl", "sanitize_package_name")
load("@rules_req_compile//private:whl_repo.bzl", "whl_repository")

def whl_repo_name(package):
    return "{repository_name}__" + sanitize_package_name(package)

def get_version(pkg):
    pkg_name = sanitize_package_name(pkg)
    return _CONSTRAINTS[pkg_name]["version"]

def requirement(name):
    return "@@" + whl_repo_name(name) + "//:pkg"

def requirements(names):
    return [
        "@@" + whl_repo_name(name) + "//:pkg"
        for name in names
    ]

def requirement_wheel(name):
    return "@@" + whl_repo_name(name) + "//:whl"

def requirements_wheels(names):
    return [
        "@@" + whl_repo_name(name) + "//:whl"
        for name in names
    ]

def entry_point(pkg, script = None):
    if not script:
        script = pkg
    return "@" + whl_repo_name(pkg) + "//:entry_point_" + script

_CONSTRAINTS = {constraints}

all_requirements = [
    requirement(name) for name in _CONSTRAINTS
]

all_requirements_wheels = [
    requirement_wheel(name) for name in _CONSTRAINTS
]

def _is_wheel(data):
    if "url" in data and data["url"]:
        if ".whl" in data["url"]:
            return True
        return False

    if "whl" in data and data["whl"]:
        return True

    return False

def _sdist_repo_name(package):
    return "{repository_name}__" + sanitize_package_name(package) + "__sdist"

def repositories():
    \"\"\"Define repositories for {repository_name}.\"\"\"
    has_sdist = False
    for name, data in _CONSTRAINTS.items():
        if _is_wheel(data):
            maybe(
                whl_repository,
                name = whl_repo_name(name),
                annotations = json.encode(data["annotations"]),
                constraint = data["constraint"],
                deps = data["deps"],
                package = name,
                reqs_repository_name = "{repository_name}",
                sha256 = data["sha256"],
                urls = [data["url"]] if data.get("url", None) else None,
                version = data["version"],
                whl = data["whl"],
            )
        else:
            has_sdist = True
            interpreter = {interpreter}
            if not interpreter:
                fail(
                    "A sdist (" + name + ") was found for the repository '{repository_name}' " +
                    "but no interpreter was provided. One is required for processing sdists."
                )
            maybe(
                sdist_repository,
                name = _sdist_repo_name(name),
                deps = ["@" + whl_repo_name(dep) + "//:BUILD.bazel" for dep in data["deps"]],
                sha256 = data["sha256"],
                urls = [data["url"]],
                interpreter = interpreter,
            )
            maybe(
                whl_repository,
                name = whl_repo_name(name),
                annotations = json.encode(data["annotations"]),
                constraint = data["constraint"],
                deps = data["deps"],
                package = name,
                reqs_repository_name = "{repository_name}",
                whl_data = "@" + _sdist_repo_name(name) + "//:whl.json",
                version = data["version"],
            )
    if has_sdist:
        print("WARNING: {repository_name} contains sdist dependencies and is not guaranteed to provide determinisitc external repositories. Using a binary-only (all wheels) solution is recommended.")

"""

RULES_PYTHON_COMPAT = """\
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
    return "@@{repository_name}" + "//:" + sanitize_package_name(name)
"""

BUILD_FILE_TEMPLATE = """\
load(":defs.bzl", "requirement", "requirement_wheel")

package(default_visibility = ["//visibility:public"])

exports_files(["defs.bzl", "requirements.bzl"])

PACKAGES = {packages}

[
    alias(
        name = pkg,
        actual = requirement(pkg),
        tags = ["manual"],
    )
    for pkg in PACKAGES
]

[
    alias(
        name = pkg + "_whl",
        actual = requirement_wheel(pkg),
        tags = ["manual"],
    )
    for pkg in PACKAGES
]

filegroup(
    name = "all_wheels",
    srcs = [
        pkg + "_whl"
        for pkg in PACKAGES
    ],
    tags = ["manual"],
)
"""

def parse_constraint(data, repository_name, lockfile, wheel_dirs):
    """Parse a section of a requirements lock file from `req-compile`.

    Args:
        data (list): The stripped lines of a constraint's section in a lock file.
        repository_name (str): The name of the current repository.
        lockfile (Label): The label of the current lockfile. Used to resolve paths to
            constraints represented by relative paths instead of urls.
        wheel_dirs (list): A list of strings that represent directories containing
            wheels, relative to the workspace root.

    Returns:
        dict: Parsed data for the constraint.
    """
    url = None
    whl = None
    if len(data) < 3:
        fail("The data given did not match the minimum expected length in {}:\n{}".format(
            repository_name,
            "\n".join(data),
        ))
    package, _, version = data[0].partition("==")
    version = version.strip(" \\")

    if not data[1].startswith("--hash=sha256:"):
        fail("Unexpected data found where a sha256 hash value was expected for {}:\n{}".format(
            package,
            data[1],
        ))
    sha256 = data[1][len("--hash=sha256:"):]

    via = []
    for entry in data[2:-1]:
        text = entry.replace("# via", "#")
        pkg, _, _ = text.strip(" #").partition(" ")
        pkg, _, _ = pkg.partition("[")
        if not pkg:
            continue

        # Skip any file paths. We only care to track packages
        if "/" in pkg or "\\" in pkg:
            continue

        via.append(sanitize_package_name(pkg))

    url = data[-1].strip(" #")
    if not url.startswith(("http://", "https://", "file://")):
        if wheel_dirs and url.startswith(*wheel_dirs):
            # If the path is a relative parent, then we use the existing
            # lockfile label to create a clean label. This logic assumes
            # the wheeldir will be in a package (but not a package itself).
            if url.startswith(("..", "./../")):
                url_parents = url.count("../")

                repository, _, path = str(lockfile).partition("//")
                lockfile_dir, _, _ = path.partition(":")

                new_package = "/".join(lockfile_dir.split("/")[:-url_parents])

                split = url.split("/")
                wheel = "{}/{}".format(split[-2], split[-1])

                whl = "{}//{}:{}".format(repository, new_package, wheel)
            else:
                whl = str(lockfile.same_package_label(url))
            url = None
        else:
            fail("Unexpected data found where url was expected for {} ({}):\n{}".format(
                repository_name,
                data[0].rstrip("\\ "),
                data[-1],
            ))

    return {
        "annotations": {},
        "constraint": None,
        "deps": [],
        "package": package,
        "sha256": sha256,
        "url": url,
        "version": version,
        "via": sorted(via),
        "whl": whl,
    }

def parse_lockfile(
        content,
        repository_name,
        annotations,
        lockfile,
        constraint = None):
    """Parse a requirements lock file into a map of constraints.

    Args:
        content (str): The string content of a requirements lock file.
        repository_name (str): The name of the current repository
        annotations (dict): Annotation data for packages in the current lock file.
        lockfile (Label): The label of the lockfile containing `content`.
        constraint (Label): An optional Label which represents the constraint value of the package.

    Returns:
        dict: A mapping of package names to it's parsed data from the constraints file.
    """
    wheel_dirs = []
    entries = []
    capturing = []
    for line in content.splitlines():
        text = line.strip()
        if text.startswith(("--index", "--extra")):
            continue
        if text.startswith(("--find-links", "--find_links")):
            text, _, _ = text.partition("#")
            wheel_dirs.append(text[len("--find-links"):].strip(" '\"=\n"))
            continue
        if capturing:
            # Stop at either the next constraint or a blank line
            if not text or not text.startswith(("#", "-")):
                entries.append(parse_constraint(
                    capturing,
                    repository_name,
                    lockfile,
                    wheel_dirs,
                ))
                capturing = []
            else:
                capturing.append(text)
                continue

        if not text or text.startswith("#"):
            continue

        capturing.append(text)

    # Process the final package if we hit the end of the file
    if capturing:
        entries.append(parse_constraint(
            capturing,
            repository_name,
            lockfile,
            wheel_dirs,
        ))

    packages = {
        sanitize_package_name(data["package"]): data
        for data in entries
    }

    for pkg, data in packages.items():
        for via in data["via"]:
            # It may be the case that an entry in `via` is the name
            # of a "requirements.in" file. Unfortunately the file name
            # can also be a valid package name so it cannot be filtered
            # out of the list. As a result, skip packages that aren't in
            # the list of packages. This means issues will be deferred
            # later on in the analysis phase.
            if via in packages:
                packages[via]["deps"].append(pkg)

    for pkg in packages:
        packages[pkg]["deps"] = sorted(packages[pkg]["deps"])
        if constraint:
            packages[pkg]["constraint"] = str(constraint)

    for package, data in annotations.items():
        package = sanitize_package_name(package)
        if package not in packages:
            fail("The package `{}` was not found in constraints. Try one of: {}".format(
                package,
                packages.keys(),
            ))

        packages[package].update({"annotations": data})

    return packages

def write_defs_file(repository_ctx, packages, defs_output, id = "", name = None):
    repository_ctx.file(defs_output, _CONSTRAINTS_BZL_TEMPLATE.format(
        constraints = json.encode_indent(packages, indent = " " * 4).replace(" null", " None"),
        repository_name = "{}_{}".format(repository_ctx.name, id).rstrip("_"),
        repository_defs = defs_output.basename,
        interpreter = repr(repository_ctx.attr.interpreter),
    ))

def process_lockfile(repository_ctx, requirements_lock, name = None, annotations = None, constraint = None):
    """Convert a lockfile into a map of packages

    Args:
        repository_ctx (repository_ctx): The repository context object
        requirements_lock (Label): The label of the lock file.
        name: Friendly name of the repository.
        annotations: The annotations to apply to the requirements from this lock.
        constraint (Label, optional): An optional constraint label associated
            with the parsed packages.

    Returns:
        dict: See `parse_lockfile`.
    """
    repository_ctx.report_progress("Parsing {}".format(requirements_lock))
    content = repository_ctx.read(repository_ctx.path(requirements_lock))

    # Skip empty files
    if not content.strip():
        return {}

    if not name:
        name = repository_ctx.name

    if annotations == None:
        annotations = repository_ctx.attr.annotations

    packages = parse_lockfile(
        content = content,
        repository_name = name,
        annotations = annotations,
        lockfile = requirements_lock,
        constraint = constraint,
    )

    return packages

def _requirements_repository_common(repository_ctx):
    repository_ctx.file("WORKSPACE.bazel", """workspace(name = "{}")""".format(
        repository_ctx.name,
    ))
    repository_ctx.file("requirements.bzl", RULES_PYTHON_COMPAT.format(
        repository_name = repository_ctx.name,
    ))

_LOAD_TEMPLATE = """\
load(
    ":defs_{id}.bzl",
    {id}_all_requirements = "all_requirements",
    {id}_all_requirements_wheels = "all_requirements_wheels",
    {id}_entry_point = "entry_point",
    {id}_get_version = "get_version",
    {id}_repositories = "repositories",
    {id}_requirement = "requirement",
    {id}_requirement_wheel = "requirement_wheel",
)
"""

_INTERFACE_BZL_TEMPLATE = """\
\"\"\"Python constraints\"\"\"
load("@rules_req_compile//private:utils.bzl", "sanitize_package_name")
{loads}

def whl_repo_name(package):
    fail("Uses of `py_requirements_repository.requirements_locks` cannot determine the correct repo name at analysis time for: " + package)

def get_version(pkg):
    return select({{
        {get_version}
    }})

def requirement(name):
    return select({{
        {requirement}
    }})

def requirements(names):
    return select({{
        {requirements}
    }})

def requirement_wheel(name):
    return select({{
        {requirement_wheel}
    }})

def requirements_wheels(names):
    return select({{
        {requirements_wheels}
    }})

def entry_point(pkg, script, output_list = False):
    if output_list:
        return select({{
            {entry_points}
        }})

    return select({{
        {entry_point}
    }})

all_requirements = select({{
    {all_requirements}
}})

all_requirements_wheels = select({{
    {all_requirements_wheels}
}})

def repositories():
    {repositories}
"""

def generate_interface_bzl_content(defs, repository_name):
    """Generate the defs.bzl file contents that selects between multiple architectures.

    Args:
        defs (dict): id -> constraint mapping dictionary.
        repository_name (str): Name of the repository containing this file.

    Returns:
        The file contents.
    """
    loads = []
    all_requirements = []
    all_requirements_wheels = []
    entry_point = []
    entry_points = []
    get_version = []
    repositories = []
    requirement = []
    requirements = []
    requirement_wheel = []
    requirements_wheels = []
    for id, constraint in defs.items():
        loads.append(_LOAD_TEMPLATE.format(id = id))
        all_requirements.append("\"{}\": {}_all_requirements,".format(constraint, id))
        all_requirements_wheels.append("\"{}\": {}_all_requirements_wheels,".format(constraint, id))
        entry_point.append("\"{}\": {}_entry_point(pkg, script),".format(constraint, id))
        entry_points.append("\"{}\": [{}_entry_point(pkg, script)],".format(constraint, id))
        get_version.append("\"{}\": {}_get_version(pkg),".format(constraint, id))
        repositories.append("{}_repositories()".format(id))
        requirement.append("\"{}\": {}_requirement(name),".format(constraint, id))
        requirements.append("\"{}\": [{}_requirement(name) for name in names],".format(constraint, id))
        requirement_wheel.append("\"{}\": {}_requirement_wheel(name),".format(constraint, id))
        requirements_wheels.append("\"{}\": [{}_requirement_wheel(name) for name in names],".format(constraint, id))

    return _INTERFACE_BZL_TEMPLATE.format(
        repository_name = repository_name,
        loads = "\n".join(loads),
        all_requirements = "\n    ".join(all_requirements),
        all_requirements_wheels = "\n    ".join(all_requirements_wheels),
        entry_point = "\n        ".join(entry_point),
        entry_points = "\n        ".join(entry_points),
        get_version = "\n        ".join(get_version),
        repositories = "\n    ".join(repositories),
        requirement = "\n        ".join(requirement),
        requirement_wheel = "\n        ".join(requirement_wheel),
        requirements = "\n        ".join(requirements),
        requirements_wheels = "\n        ".join(requirements_wheels),
    )

def _py_requirements_repository_impl(repository_ctx):
    if repository_ctx.attr.requirements_lock and repository_ctx.attr.requirements_locks:
        fail("`requirements_lock` and `requirements_locks` are mutually exclusive for `py_requirements_repository`. Please update {}".format(
            repository_ctx.name,
        ))
    if repository_ctx.attr.requirements_lock:
        packages = process_lockfile(
            repository_ctx = repository_ctx,
            requirements_lock = repository_ctx.attr.requirements_lock,
        )

        write_defs_file(repository_ctx, packages, repository_ctx.path("defs.bzl"))

        repository_ctx.file("BUILD.bazel", BUILD_FILE_TEMPLATE.format(
            packages = json.encode_indent(sorted(packages.keys()), indent = " " * 4),
        ))

        _requirements_repository_common(repository_ctx)
    elif repository_ctx.attr.requirements_locks:
        all_packages = []
        defs = {}
        for lock, constraint in repository_ctx.attr.requirements_locks.items():
            constraint = str(Label(constraint))
            lockfile = repository_ctx.path(lock)

            defs_id, _, _ = lockfile.basename.rpartition(".")
            defs_id = defs_id.replace("requirements", "").replace(".", "_").replace("-", "_").strip(" -_.")
            defs.update({defs_id: constraint})

            defs_file = repository_ctx.path("defs_{}.bzl".format(defs_id))

            packages = process_lockfile(
                repository_ctx = repository_ctx,
                requirements_lock = lock,
                constraint = constraint,
            )
            all_packages.extend(packages.keys())

            write_defs_file(repository_ctx, packages, defs_file, defs_id)

        repository_ctx.file("defs.bzl", generate_interface_bzl_content(defs, repository_ctx.name))
        repository_ctx.file("BUILD.bazel", BUILD_FILE_TEMPLATE.format(
            packages = json.encode_indent(sorted(depset(all_packages).to_list()), indent = " " * 4),
        ))
        _requirements_repository_common(repository_ctx)
    else:
        fail("Either `requirements_lock` or `requirements_locks` must be set for `py_requirements_repository`. Please update {}".format(
            repository_ctx.name,
        ))

py_requirements_repository = repository_rule(
    doc = """\
A rule for importing `requirements.txt` dependencies into Bazel.

Those dependencies become available in a generated `defs.bzl` file.

```python
load("@rules_req_compile//:defs.bzl", "py_requirements_repository")

py_requirements_repository(
    name = "py_requirements",
    requirements_lock = ":requirements.txt",
)

load("@py_requirements//:defs.bzl", "repositories")

repositories()
```

You can then reference installed dependencies from a `BUILD` file with:

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

In addition to the `requirement` macro, which is used to access the generated `py_library`
target generated from a package's wheel, The generated `requirements.bzl` file contains
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
case where a sdist (source distribution) is found in a solution file passed to either
`requirements_lock` or `requirements_locks`, the dependencies should not be considered
byte-for-byte reproducible. It is highly recommended solution files contain all wheels
so the generated repositories are byte-for-byte consistent. Failure to use binary-only
dependencies will result in unexpected cache invalidation as well as inconsistent or broken
cross-platform behavior when using `requirements_locks`.
""",
    implementation = _py_requirements_repository_impl,
    attrs = {
        "annotations": attr.string_dict(
            doc = (
                "Optional annotations to apply to packages. For details see " +
                "[@rules_python//python:pip.bzl%package_annotation](https://github.com/bazelbuild/rules_python/blob/main/docs/pip_repository.md#package_annotation)"
            ),
        ),
        "interpreter": attr.label(
            doc = (
                "The label of a python interpreter to use for compiling source distributions (sdists). If " +
                "this is not provided then the provided lock file must represent binary-only dependencies. " +
                "Note that should this interpreter be needed (a sdist was found in `requirements_lock` or " +
                "`requirements_locks`), the dependencies generated may not be byte-for-byte reproducible and " +
                "users may experience unexpected cache invalidation or unexpected cross-platform behavior."
            ),
            allow_files = True,
        ),
        "requirements_lock": attr.label(
            doc = (
                "A fully resolved 'requirements.txt' pip requirement file containing " +
                "the transitive set of your dependencies. This file _must_ be produced by " +
                "[req-compile](https://pypi.org/project/req-compile/) and include hashes and urls " +
                "in the solution. This attribute is mutually exclusive with `requirements_locks`."
            ),
            allow_files = True,
        ),
        "requirements_locks": attr.label_keyed_string_dict(
            doc = (
                "A map of fully resolved 'requirements.txt' pip requirement file containing " +
                "the transitive set of your dependencies to labels of Bazel [platforms](https://bazel.build/extending/platforms). " +
                "These requirements files __must__ be produced by [req-compile](https://pypi.org/project/req-compile/) " +
                "and include hashes and urls in the solution. Each lock file provided will create " +
                "a dependency tree matching `{name}_{id}__{package}` where `id` is the name " +
                "of the lock file with `[\".\", \"-\"]` characters are replaced by `\"_\"` " +
                "and the name `requirements` will be stripped. This means each `requirements_locks` " +
                "entry will need to be somewhat uniquely named. This attribute is mutually " +
                "exclusive with `requirements_lock`."
            ),
            allow_files = True,
            allow_empty = False,
        ),
    },
)
