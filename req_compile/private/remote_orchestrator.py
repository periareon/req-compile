"""A script responsible for running a `py_req_compiler` target on a remote system."""

import argparse
import os
import subprocess
from pathlib import Path

from python.runfiles import Runfiles  # pylint: disable=import-error


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "ssh_host", type=str, help="The ssh user and host to compile on."
    )
    parser.add_argument(
        "compiler_args",
        nargs="*",
        help="Remaining arguments to forward to the compiler.",
    )

    return parser.parse_args()


def main() -> None:
    """The main entrypoint."""
    args = parse_args()

    # Find the zipapp
    runfiles = Runfiles.Create()
    assert runfiles, "Failed to find runfiles."

    compiler = runfiles.Rlocation(os.environ["COMPILER"])
    assert compiler, "Failed to find compiler"

    compiler_path = Path(compiler)

    # Copy it to the remote machine
    subprocess.run(
        ["scp", compiler, f"{args.ssh_host}://tmp/{compiler_path.name}"], check=True
    )

    # Execute it and then remove it
    compiler_args = " ".join(args.compiler_args)
    bash_command = f'bash -c \'python3 "/tmp/{compiler_path.name}" {compiler_args} ; rm -f "/tmp/{compiler_path.name}"\''  # pylint: disable=line-too-long
    subprocess.run(["ssh", "-t", args.ssh_host, bash_command], check=True)


if __name__ == "__main__":
    main()
