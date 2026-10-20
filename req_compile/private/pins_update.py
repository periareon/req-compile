"""Write the pinned requirements a hub rendered into the workspace.

Run through `bazel run @<hub>//:requirements.update`; the arguments are the
runfiles path of the rendered file and the workspace-relative path to write.
"""

import os
import sys

# pylint: disable-next=import-error
from python.runfiles import Runfiles


def main() -> None:
    """The main entrypoint."""
    rendered, destination = sys.argv[1:3]
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
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    print("Wrote {}".format(destination))


if __name__ == "__main__":
    main()
