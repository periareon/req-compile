"""Parsing of lock files produced by `req-compile`."""

load(":utils.bzl", "sanitize_package_name")

def parse_constraint(data, lockfile, wheel_dirs):
    """Parse a section of a requirements lock file from `req-compile`.

    Args:
        data (list): The stripped lines of a constraint's section in a lock file.
        lockfile (Label): The label of the current lockfile. Used to resolve paths to
            constraints represented by relative paths instead of urls.
        wheel_dirs (list): A list of strings that represent directories containing
            wheels, relative to the workspace root.

    Returns:
        dict: Parsed data for the constraint.
    """
    url = None
    whl = None

    if "==" not in data[0]:
        fail("Unexpected line in constraints file: {}".format(data))

    package, _, version = data[0].partition("==")
    version = version.strip(" \\")

    if len(data) > 1 and data[1].startswith("--hash=sha256:"):
        sha256 = data[1][len("--hash=sha256:"):]
    else:
        sha256 = ""

    via = {}
    if len(data) > 2:
        for entry in data[2:-1]:
            text = entry.replace("# via", "#")
            pkg, _, _ = text.strip(" #").partition(" ")

            # Extras are recorded on the reverse dependency, e.g. `requests[socks]`. The
            # dependency edge is the same regardless of which extra introduced it.
            pkg, _, _ = pkg.partition("[")
            if not pkg:
                continue

            # Skip any file paths. We only care to track packages.
            if "/" in pkg or "\\" in pkg:
                continue

            via[sanitize_package_name(pkg)] = 1

    whl = None
    if len(data) >= 4:
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
                url = None

    return {
        "annotations": {},
        "constraint": None,
        "deps": [],
        "package": package,
        "sha256": sha256,
        "url": url,
        "version": version,
        "via": sorted(via) if via else None,
        "whl": whl,
    }

def parse_lockfile(
        content,
        annotations,
        lockfile,
        constraint = None):
    """Parse a requirements lock file into a map of constraints.

    Args:
        content (str): The string content of a requirements lock file.
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
            lockfile,
            wheel_dirs,
        ))

    packages = {
        sanitize_package_name(data["package"]): data
        for data in entries
    }

    for pkg, data in packages.items():
        if data["via"] == None:
            continue
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
            continue

        packages[package].update({"annotations": data})

    return packages

def parse_lock_header(content):
    """Parse the header `req-compile` writes to lock files compiled by Bazel.

    The header records the platform and Python version the solution was
    compiled for, e.g.

    ```
    ## Python: 3.11
    ## Platform: linux_x86_64
    ```

    Args:
        content (str): The content of the lock file.

    Returns:
        struct: With `platform` and `python` members, either of which may be None.
    """
    platform = None
    python = None
    for line in content.splitlines():
        text = line.strip()
        if not text:
            continue
        if not text.startswith("#"):
            break
        text = text.strip("# ")
        if text.startswith("Platform:"):
            platform = text[len("Platform:"):].strip() or None
        elif text.startswith("Python:"):
            python = text[len("Python:"):].strip() or None
    return struct(
        platform = platform,
        python = python,
    )
