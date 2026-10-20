"""Write the pinned requirements a hub rendered into the workspace.

Run through `bazel run @<hub>//:requirements.update`. The arguments are the
runfiles path of the rendered file, the workspace-relative path to write and
this target's canonical label; `--upgrade` (`-U`), with or without package
names, resolves again from the index for those packages, every package without
names, by running that label once more with `--repo_env=REQ_COMPILE_UPGRADE=...`
(the canonical label works whatever the hub is called in the root module; the
`--repo_env` is seen whatever `.bazelrc` sets for the variable).

The inner command is `bazel` from PATH, or `$BAZEL`, with no option of the outer
command line: options the resolution needs belong in `.bazelrc`. And since the
outer `bazel run` has to resolve the hub before this script starts, a hash in
the file that keeps the hub from resolving at all is lifted from the shell
instead: `REQ_COMPILE_UPGRADE=<package>[,<package>] bazel run @<hub>//:requirements.update`
(`all` for every package).
"""

import argparse
import os
import subprocess
import sys
from typing import List, Optional

UPGRADE_ENV = "REQ_COMPILE_UPGRADE"


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bazel run @<hub>//:requirements.update --",
        description="Write the pinned requirements the hub resolved.",
    )
    parser.add_argument("rendered", help=argparse.SUPPRESS)
    parser.add_argument("destination", help=argparse.SUPPRESS)
    parser.add_argument("target", help=argparse.SUPPRESS)
    parser.add_argument(
        "-U",
        "--upgrade",
        nargs="*",
        metavar="PACKAGE",
        help=(
            "Move the named packages' pins: resolve them again from the index, "
            "ignoring their pins in the file (every package when no name is given), "
            "then write the file and the lock."
        ),
    )
    return parser.parse_args(argv)


def upgrade_command(names: List[str], target: str, bazel: str = "bazel") -> List[str]:
    """The command that runs `target` again with the named packages' pins lifted."""
    wanted = sorted({name.strip() for name in names if name.strip()})
    value = ",".join(wanted) if wanted else "all"
    return [bazel, "run", "--repo_env={}={}".format(UPGRADE_ENV, value), target]


def _upgrade(args: argparse.Namespace) -> int:
    """Run this target again with `REQ_COMPILE_UPGRADE` set, so the hub re-solves."""
    workspace = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
    if not workspace:
        raise EnvironmentError(
            "Run this with `bazel run`; it writes into the workspace."
        )
    command = upgrade_command(
        args.upgrade, args.target, os.environ.get("BAZEL", "bazel")
    )
    print(
        "Resolving {} again: {}".format(
            ", ".join(sorted(args.upgrade)) if args.upgrade else "every package",
            " ".join(command),
        ),
        file=sys.stderr,
    )
    return subprocess.call(command, cwd=workspace)


def _write(args: argparse.Namespace) -> None:
    """Write the rendered file into the workspace."""
    # Imported here so that the command can be imported and tested without it.
    # pylint: disable-next=import-error,import-outside-toplevel
    from python.runfiles import Runfiles

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


def main() -> None:
    """The main entrypoint."""
    args = _parse_args()
    if args.upgrade is not None:
        sys.exit(_upgrade(args))
    _write(args)


if __name__ == "__main__":
    main()
