"""Write the pinned requirements a hub rendered into the workspace.

Run through `bazel run @<hub>//:requirements.update`. The arguments are the
runfiles path of the rendered file and the workspace-relative path to write.
A file that is already up to date is left alone.

To move a pin on purpose, set `REQ_COMPILE_UPGRADE` on that command:
`REQ_COMPILE_UPGRADE=<package>[,<package>] bazel run @<hub>//:requirements.update`
(`all` for every package). The extension reads the variable and resolves the
named packages again from the index, ignoring their pins in the file; this
script only writes what the hub rendered.

`MODULE.bazel.lock` records the file as it was when the hub resolved, before
this script rewrote it; the next Bazel command brings the lock up to date, or
`bazel mod deps --lockfile_mode=update` does so at once.
"""

import os
import sys


def main() -> None:
    """The main entrypoint."""
    # Imported here so that the module can be imported without the runfiles library.
    # pylint: disable-next=import-error,import-outside-toplevel
    from python.runfiles import Runfiles

    rendered, destination = sys.argv[1:3]
    if len(sys.argv) > 3:
        sys.exit(
            "requirements.update takes no arguments (got {}). To move a pin, set "
            "REQ_COMPILE_UPGRADE=<package>[,<package>] on the command, `all` for "
            "every package.".format(" ".join(sys.argv[3:]))
        )
    runfiles = Runfiles.Create()
    if not runfiles:
        raise EnvironmentError("Failed to locate runfiles.")
    source = runfiles.Rlocation(rendered)
    if not source:
        raise EnvironmentError("Failed to locate {}".format(rendered))
    workspace = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
    if not workspace:
        raise EnvironmentError(
            "Run this with `bazel run`; it writes into the workspace."
        )
    target = os.path.join(workspace, destination)
    with open(source, "r", encoding="utf-8") as handle:
        content = handle.read()
    if os.path.exists(target):
        with open(target, "r", encoding="utf-8") as handle:
            if handle.read() == content:
                print("{} is up to date".format(destination))
                return
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    print("Wrote {}".format(destination))


if __name__ == "__main__":
    main()
