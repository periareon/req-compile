"""Fail when a hub's pinned requirements file no longer matches its solution.

The arguments are the runfiles paths of the rendered file and of the checked-in
file, and the command that regenerates the latter.
"""

import difflib
import sys

# pylint: disable-next=import-error
from python.runfiles import Runfiles

_WARNING = """\

################################################################################

{destination} is out of date: it no longer matches what the hub resolved.

Please run the following command to update it:

    {command}
"""


def main() -> None:
    """The main entrypoint."""
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
            texts.append(handle.read().replace("\r\n", "\n"))
    expected, actual = texts[0], texts[1]
    if expected == actual:
        return
    sys.stdout.writelines(
        difflib.unified_diff(
            actual.splitlines(keepends=True),
            expected.splitlines(keepends=True),
            fromfile=destination,
            tofile=destination + " (resolved)",
        )
    )
    print(_WARNING.format(destination=destination, command=command), file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
