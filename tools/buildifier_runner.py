#!/usr/bin/env python3

import os
import subprocess
import sys
from pathlib import Path

from python.runfiles import Runfiles  # pylint: disable=import-error


DEFAULT_ARGS = [
    "-mode=fix",
    "-v=false",
    "-lint=fix",
    "--warnings=all",
    "-diff_command=diff -u",
]

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "bazel-bin",
    "bazel-out",
    "bazel-testlogs",
}


def _find_buildifier() -> str:
    runfiles = Runfiles.Create()
    if not runfiles:
        raise EnvironmentError("Failed to locate runfiles.")

    rlocationpath = os.environ.get("BUILDIFIER_BIN_RLOCATION")
    if not rlocationpath:
        raise EnvironmentError("BUILDIFIER_BIN_RLOCATION is not set.")

    runfile = runfiles.Rlocation(rlocationpath)
    if not runfile:
        raise FileNotFoundError(f"Failed to find runfile: {rlocationpath}")

    path = Path(runfile)
    if not path.exists():
        raise FileNotFoundError(f"Runfile does not exist: ({rlocationpath}) {path}")

    return str(path)


def _is_target_file(name: str) -> bool:
    return (
        name.endswith((".bzl", ".sky", ".bazel", ".BUILD"))
        or name in ("BUILD", "WORKSPACE", "WORKSPACE.bzlmod", "WORKSPACE.oss")
        or name.startswith("BUILD.") and name.endswith(".oss")
        or name.startswith("WORKSPACE.") and name.endswith(".oss")
    )


def _collect_files(root: Path) -> list[str]:
    result: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d
            for d in dirnames
            if d not in EXCLUDED_DIRS and not d.startswith("bazel-")
        ]
        base = Path(dirpath)
        for name in filenames:
            if _is_target_file(name):
                result.append(str((base / name).relative_to(root)))
    return result


def main() -> int:
    workspace = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
    if workspace:
        os.chdir(workspace)

    buildifier = _find_buildifier()
    user_args = sys.argv[1:]
    if user_args:
        cmd = [buildifier] + user_args
        return subprocess.call(cmd)

    files = _collect_files(Path("."))
    if not files:
        return 0

    cmd = [buildifier] + DEFAULT_ARGS + files
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
