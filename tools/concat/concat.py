"""Concatenate text files into a single output file.

Used to assemble the long description of the `req-compile` wheel from the
changelog and readme without relying on platform specific shell commands.
"""

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        dest="inputs",
        action="append",
        required=True,
        type=Path,
        help="A file to append to the output. May be passed multiple times.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="The path of the concatenated output file.",
    )
    parser.add_argument(
        "--separator",
        default="\n",
        help="Text to insert between each input file.",
    )
    return parser.parse_args()


def main() -> None:
    """The main entrypoint."""
    args = parse_args()

    contents = [path.read_text(encoding="utf-8") for path in args.inputs]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(args.separator.join(contents), encoding="utf-8")


if __name__ == "__main__":
    main()
