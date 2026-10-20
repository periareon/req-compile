"""Render the pinned requirements file of a hub resolved in the extension.

The file is the pin list a human reviews and a bot such as Dependabot edits:
one entry per package with its version, the sha256 of every artifact chosen for
the hub's platforms, and the packages that require it. Fed back to the hub as
`requirements_txt`, it pins exactly those versions and hashes.
"""

def _requirer_names(locks):
    """Package key to the keys of the packages requiring it, over every platform."""
    requirers = {}
    for packages in locks.values():
        for key, data in packages.items():
            for dep in data["deps"]:
                requirers.setdefault(dep, {})[key] = True
    return requirers

def render_pins(hub, locks, index_urls, roots, command):
    """The text of the pinned requirements file.

    Args:
        hub (str): The name of the hub.
        locks (dict): Platform to packages, in the shape `parse_lockfile` returns.
        index_urls (list[str]): The hub's indexes, the first being `index_url`.
        roots (list[str]): How to name the requirement files the solution came from.
        command (str): The command regenerating the file, for the header.

    Returns:
        str: The file.
    """
    entries = {}
    for packages in locks.values():
        for key, data in packages.items():
            entry = entries.setdefault(key, {
                "hashes": {},
                "package": data["package"],
                "version": data["version"],
            })
            if data["sha256"]:
                entry["hashes"][data["sha256"]] = True
    requirers = _requirer_names(locks)

    lines = [
        "# Python requirements pinned by the `{}` hub, from {}.".format(hub, ", ".join(roots)),
        "# Regenerate after changing them with:",
        "#",
        "#     {}".format(command),
        "#",
        "# A version bumped here, with its hashes, is what the hub resolves to next",
        "# (Dependabot's pip updater does this). The hashes are those of the",
        "# artifacts the hub's platforms use.",
    ]
    if index_urls:
        lines.append("--index-url {}".format(index_urls[0]))
        for url in index_urls[1:]:
            lines.append("--extra-index-url {}".format(url))
    lines.append("")
    for key in sorted(entries):
        entry = entries[key]
        hashes = sorted(entry["hashes"])
        spec = "{}=={}".format(entry["package"], entry["version"])
        if hashes:
            lines.append(spec + " \\")
            for index, sha256 in enumerate(hashes):
                tail = " \\" if index + 1 < len(hashes) else ""
                lines.append("    --hash=sha256:{}{}".format(sha256, tail))
        else:
            lines.append(spec)
        via = sorted(requirers.get(key, {}).keys())
        lines.append("    # via {}".format(", ".join(via) if via else ", ".join(roots)))
    return "\n".join(lines) + "\n"
