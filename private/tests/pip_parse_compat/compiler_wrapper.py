"""A small wrapper to a `py_reqs_compiler` that configures a required wheeldir for the find_links tests."""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    """The main entrypoint."""

    if "BUILD_WORKSPACE_DIRECTORY" not in os.environ:
        raise EnvironmentError(
            "BUILD_WORKSPACE_DIRECTORY is not defined, is the script running under Bazel?"
        )

    workspace_dir = Path(os.environ["BUILD_WORKSPACE_DIRECTORY"])

    environ = dict(os.environ)
    for to_delete in (
        "PYTHONPATH",
        "PYTHONPATHSAFE",
        "BUILD_WORKSPACE_DIRECTORY",
        "BUILD_WORKING_DIRECTORY",
        "BAZELISK_SKIP_WRAPPER",
    ):
        if to_delete in environ:
            del environ[to_delete]

    subprocess.run(
        [
            "bazel",
            "run",
            "//private/tests/pip_parse_compat:requirements.update",
            "--",
        ]
        + sys.argv[1:],
        cwd=workspace_dir,
        check=True,
        env=environ,
    )

    output = workspace_dir / "private/tests/pip_parse_compat/requirements.txt"
    for plat in ("windows", "linux", "macos"):
        shutil.copy(output, output.parent / f"requirements.{plat}.txt")


if __name__ == "__main__":
    main()
