"""A script used to avoid https://github.com/bazelbuild/bazel/issues/21747"""

import argparse
import shutil
from pathlib import Path


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser()

    parser.add_argument("src", type=Path, help="The source file.")
    parser.add_argument("dest", type=Path, help="The destination path.")

    return parser.parse_args()


def main() -> None:
    """The main entrypoint"""
    args = parse_args()

    args.dest.parent.mkdir(exist_ok=True, parents=True)
    shutil.copy2(args.src, args.dest)


if __name__ == "__main__":
    main()
