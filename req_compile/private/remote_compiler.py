"""A script for running a `py_req_compiler` target."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from python.runfiles import Runfiles  # pylint: disable=import-error


def main() -> None:
    """The  main entrypoint."""

    runfiles = Runfiles.Create()
    assert runfiles, "Failed to find runfiles."

    compiler = runfiles.Rlocation(os.environ["COMPILER"])
    assert compiler, "Failed to find compiler"

    solution_rlocationpath = os.environ["PY_REQ_COMPILER_SOLUTION_FILE"]
    solution_file = runfiles.Rlocation(solution_rlocationpath)
    assert solution_file, "Failed to find solution file"

    with tempfile.TemporaryDirectory(prefix="req-compile-") as tmp:

        # Copy the solution ito the workspace to match the behavior of local runs
        _, _, dest = solution_rlocationpath.partition("/")
        dest_path = Path(tmp) / dest
        dest_path.parent.mkdir(exist_ok=True, parents=True)
        shutil.copyfile(solution_file, dest_path)

        env = dict(os.environ)
        env["BUILD_WORKSPACE_DIRECTORY"] = tmp
        subprocess.run(
            [
                sys.executable,
                compiler,
            ]
            + sys.argv[1:],
            env=env,
            check=True,
        )

        print(dest_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
