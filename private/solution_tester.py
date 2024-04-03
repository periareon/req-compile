"""A tool which tests whether or not a given solution file satisfies a set of requirements."""

import os
import sys

# pylint: disable-next=import-error
from rules_python.python.runfiles import Runfiles

# pylint: disable-next=import-error
from private.compiler import compile_main, init_logging, parse_args, rlocation

_WARNING = """\

################################################################################

The solution file {solution} is out of date.

Please run the following command to update it:

    {custom_compile_command}
"""


def main() -> None:
    """The main entrypoint."""

    runfiles = Runfiles.Create()
    if not runfiles:
        raise EnvironmentError("Failed to locate runfiles.")

    argv = None
    if "PY_REQ_COMPILER_ARGS_FILE" in os.environ:
        args_file = rlocation(runfiles, os.environ["PY_REQ_COMPILER_ARGS_FILE"])
        argv = args_file.read_text(encoding="utf-8").splitlines()

    args = parse_args(argv)

    init_logging(args.verbose)

    try:
        compile_main(args, runfiles)
    except SystemExit as exc:
        if exc.code == 1:
            print(
                _WARNING.format(
                    solution=args.solution,
                    custom_compile_command=args.custom_compile_command,
                ),
                file=sys.stderr,
            )
        raise


if __name__ == "__main__":
    main()
