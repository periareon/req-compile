"""Fail when a hub's pinned requirements file no longer pins what the hub resolved.

The comparison is by meaning, not by text: the file passes when it pins exactly
the packages the hub resolved, at the hub's versions, and for each package its
hashes include the sha256 of every artifact the hub's platforms chose. Extra
hashes (pip-compile writes the hash of every file of a release, Dependabot
regenerates the file with pip-compile), comments, ordering, the header and
option lines do not matter.

The arguments are the runfiles paths of the rendered file and of the workspace's
copy, the workspace path of the latter, and the command that regenerates it.
"""

import re
import sys
from typing import Dict, List, Set, Tuple

_WARNING = """\

################################################################################

{destination} is out of date: it no longer pins what the hub resolved.

{problems}

Please run the following command to update it:

    {command}
"""

Pins = Dict[str, Tuple[str, Set[str]]]


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_pins(text: str) -> Pins:
    """The `name==version` pins of a requirements file with their sha256 hashes.

    Comments, blank lines and option lines are skipped, continuation lines are
    joined, markers and extras are ignored, and both `--hash=sha256:...` and
    `--hash sha256:...` are read.
    """
    pins: Pins = {}
    logical = ""
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        comment = line.find(" #")
        if comment != -1:
            line = line[:comment].rstrip()
        if line.endswith("\\"):
            logical += line[:-1] + " "
            continue
        entry, logical = (logical + line).strip(), ""
        if not entry or entry.startswith("-"):
            continue
        parts = entry.split()
        hashes: Set[str] = set()
        spec_parts: List[str] = []
        index = 0
        while index < len(parts):
            part = parts[index]
            index += 1
            if part == "--hash" and index < len(parts):
                value = parts[index]
                index += 1
            elif part.startswith("--hash="):
                value = part[len("--hash=") :]
            else:
                if not part.startswith("--"):
                    spec_parts.append(part)
                continue
            algorithm, _, digest = value.partition(":")
            if algorithm == "sha256":
                hashes.add(digest.lower())
        spec = " ".join(spec_parts).split(";", maxsplit=1)[0].strip()
        match = re.match(
            r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*==\s*(\S+)$", spec
        )
        if not match:
            continue
        name, version = _normalize(match.group(1)), match.group(3)
        if name in pins:
            pins[name] = (pins[name][0], pins[name][1] | hashes)
        else:
            pins[name] = (version, hashes)
    return pins


def compare(resolved: Pins, pinned: Pins) -> List[str]:
    """What keeps `pinned` from pinning `resolved`; empty when it does."""
    problems = []
    for name in sorted(set(resolved) | set(pinned)):
        if name not in pinned:
            problems.append(
                "`{0}` is missing: the hub resolved {0}=={1}".format(
                    name, resolved[name][0]
                )
            )
            continue
        if name not in resolved:
            problems.append(
                "`{}` is pinned to {} but the hub did not resolve it".format(
                    name, pinned[name][0]
                )
            )
            continue
        version, hashes = resolved[name]
        pinned_version, pinned_hashes = pinned[name]
        if pinned_version != version:
            problems.append(
                "`{}` is pinned to {} but the hub resolved {}".format(
                    name, pinned_version, version
                )
            )
            continue
        missing = sorted(hashes - pinned_hashes)
        if missing:
            problems.append(
                "`{}` lacks the hash of an artifact the hub uses: {}".format(
                    name, ", ".join(sha256[:12] for sha256 in missing)
                )
            )
    return problems


def main() -> None:
    """The main entrypoint."""
    # Imported here so that the comparison can be imported and tested without it.
    # pylint: disable-next=import-error,import-outside-toplevel
    from python.runfiles import Runfiles

    rendered, checked_in, destination, command = sys.argv[1:5]
    runfiles = Runfiles.Create()
    if not runfiles:
        raise EnvironmentError("Failed to locate runfiles.")
    texts = []
    for path in (rendered, checked_in):
        located = runfiles.Rlocation(path)
        if not located:
            raise EnvironmentError("Failed to locate {}".format(path))
        with open(located, "r", encoding="utf-8") as handle:
            texts.append(handle.read())
    problems = compare(parse_pins(texts[0]), parse_pins(texts[1]))
    if not problems:
        return
    print(
        _WARNING.format(
            destination=destination,
            problems="\n".join("  - " + problem for problem in problems),
            command=command,
        ),
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
