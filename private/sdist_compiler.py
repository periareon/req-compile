"""A tool for building wheels from a given sdist artifact."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict


def parse_args() -> argparse.Namespace:
    """Parse command line arguments"""
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--sdist",
        type=Path,
        required=True,
        help="The path to an sdist artifact.",
    )

    parser.add_argument(
        "--data_output",
        type=Path,
        required=True,
        help="An output path for json serialized data about the built wheel.",
    )

    return parser.parse_args()


def configure_reproducible_wheels(environ: Dict[str, str]) -> Dict[str, str]:
    """Modifies the environment to make wheel building reproducible.
    Wheels created from sdists are not reproducible by default. We can however workaround this by
    patching in some configuration with environment variables.
    """

    # wheel, by default, enables debug symbols in GCC. This incidentally captures the build path in the .so file
    # We can override this behavior by disabling debug symbols entirely.
    # https://github.com/pypa/pip/issues/6505
    if "CFLAGS" in environ:
        environ["CFLAGS"] += " -g0"
    else:
        environ["CFLAGS"] = "-g0"

    # set SOURCE_DATE_EPOCH to 1980 so that we can use python wheels
    # https://github.com/NixOS/nixpkgs/blob/master/doc/languages-frameworks/python.section.md#python-setuppy-bdist_wheel-cannot-create-whl
    if "SOURCE_DATE_EPOCH" not in environ:
        environ["SOURCE_DATE_EPOCH"] = "315532800"

    # Python wheel metadata files can be unstable.
    # See https://bitbucket.org/pypa/wheel/pull-requests/74/make-the-output-of-metadata-files/diff
    if "PYTHONHASHSEED" not in environ:
        environ["PYTHONHASHSEED"] = "0"

    return environ


def sha256sum(filename: Path) -> str:
    """Compute the sha256 checksum of a file.

    Args:
        filename: The file to hash.

    Returns:
        The sha256 value.
    """
    builder = hashlib.sha256()
    with filename.open("rb") as file:
        chunk = file.read(4096)
        while chunk:
            builder.update(chunk)
            chunk = file.read(4096)
    return builder.hexdigest()


def main() -> None:
    """The main entrypoint"""
    args = parse_args()

    environ = configure_reproducible_wheels(dict(os.environ))

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--progress-bar=off",
            "--no-deps",
            "--isolated",
            "--disable-pip-version-check",
            "--wheel-dir",
            Path.cwd(),
            args.sdist,
        ],
        check=True,
        env=environ,
    )

    wheel = None
    for item in Path.cwd().iterdir():
        if item.name.endswith(".whl"):
            wheel = item
            break

    if not wheel:
        raise FileNotFoundError(f"No wheel was found for {args.sdist}")

    data = {
        "wheel": wheel.name,
        "sha256": sha256sum(wheel),
    }

    args.data_output.write_text(json.dumps(data, indent=" " * 4), encoding="utf-8")


if __name__ == "__main__":
    main()
