"""Write the pinned requirements a hub rendered into the workspace.

Run through `bazel run @<hub>//:requirements.update`. The arguments are the
runfiles path of the rendered file, the workspace-relative path to write and
the hub's name; `--upgrade` (`-U`), with or without package names, resolves
again from the index for those packages, every package without names, by
running the same target once more with `REQ_COMPILE_UPGRADE` set.
"""

import argparse
import os
import subprocess
import sys
from typing import List, Optional

# pylint: disable-next=import-error
from python.runfiles import Runfiles


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bazel run @<hub>//:requirements.update --",
        description="Write the pinned requirements the hub resolved.",
    )
    parser.add_argument("rendered", help=argparse.SUPPRESS)
    parser.add_argument("destination", help=argparse.SUPPRESS)
    parser.add_argument("hub", help=argparse.SUPPRESS)
    parser.add_argument(
        "-U",
        "--upgrade",
        nargs="*",
        metavar="PACKAGE",
        help=(
            "Resolve the named packages again from the index, ignoring their pins "
            "in the file (every package when no name is given), then write the file."
        ),
    )
    return parser.parse_args(argv)


def _upgrade(args: argparse.Namespace) -> int:
    """Run this target again with `REQ_COMPILE_UPGRADE` set, so the hub re-solves."""
    workspace = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
    if not workspace:
        raise EnvironmentError(
            "Run this with `bazel run`; it writes into the workspace."
        )
    names = sorted({name.strip() for name in args.upgrade if name.strip()})
    env = dict(os.environ)
    env["REQ_COMPILE_UPGRADE"] = ",".join(names) if names else "all"
    bazel = os.environ.get("BAZEL", "bazel")
    command = [bazel, "run", "@{}//:requirements.update".format(args.hub)]
    print(
        "Resolving {} again: REQ_COMPILE_UPGRADE={} {}".format(
            ", ".join(names) if names else "every package",
            env["REQ_COMPILE_UPGRADE"],
            " ".join(command),
        ),
        file=sys.stderr,
    )
    return subprocess.call(command, cwd=workspace, env=env)


def main() -> None:
    """The main entrypoint."""
    args = _parse_args()
    if args.upgrade is not None:
        sys.exit(_upgrade(args))

    runfiles = Runfiles.Create()
    if not runfiles:
        raise EnvironmentError("Failed to locate runfiles.")
    source = runfiles.Rlocation(args.rendered)
    if not source:
        raise EnvironmentError("Failed to locate {}".format(args.rendered))
    workspace = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
    if not workspace:
        raise EnvironmentError(
            "Run this with `bazel run`; it writes into the workspace."
        )
    target = os.path.join(workspace, args.destination)
    with open(source, "r", encoding="utf-8") as handle:
        content = handle.read()
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    print("Wrote {}".format(args.destination))


if __name__ == "__main__":
    main()
