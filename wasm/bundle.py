#!/usr/bin/env python3
"""Pack Python sources into the bundle format `bootstrap.py` reads.

Usage: bundle.py --out bundle.bin [--root DIR]... [--stdlib DIR]

Every `--root` is a directory whose contents are importable from its top, e.g. a
checkout containing `req_compile/`. `--stdlib` is a CPython `Lib` directory,
trimmed of the parts a solver never needs.
"""

import argparse
import marshal
import os
import struct
import sys

MAGIC = b"RQB1"

STDLIB_SKIP = {
    "__phello__",
    "__pycache__",
    "ctypes",
    "ensurepip",
    "idlelib",
    "lib-dynload",
    "lib2to3",
    "pydoc_data",
    "site-packages",
    "test",
    "tkinter",
    "turtledemo",
    "venv",
}


def collect(root, skip):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in skip
            and not d.endswith(".dist-info")
            and not d.startswith("config-")
        )
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            yield os.path.relpath(path, root).replace(os.sep, "/"), path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--root", action="append", default=[])
    parser.add_argument("--stdlib")
    parser.add_argument(
        "--pyc",
        action="store_true",
        help="store compiled bytecode instead of source; the running interpreter must be the "
        "same minor version as the one embedded in the module",
    )
    args = parser.parse_args()

    entries = {}
    if args.stdlib:
        for name, path in collect(args.stdlib, STDLIB_SKIP):
            entries[name] = path
    for root in args.root:
        for name, path in collect(root, {"__pycache__", "tests", "test"}):
            entries[name] = path

    total = 0
    with open(args.out, "wb") as out:
        out.write(MAGIC)
        for name in sorted(entries):
            with open(entries[name], "rb") as handle:
                data = handle.read()
            if args.pyc:
                try:
                    code = compile(data, "/bundle/" + name, "exec", dont_inherit=True)
                except SyntaxError:
                    # Some stdlib files are templates or deliberately invalid; skip them.
                    continue
                data = marshal.dumps(code)
                name = name[: -len(".py")] + ".pyc"
            encoded = name.encode("utf-8")
            out.write(struct.pack("<I", len(encoded)))
            out.write(encoded)
            out.write(struct.pack("<I", len(data)))
            out.write(data)
            total += len(data)
    kind = (
        f"bytecode for Python {sys.version_info.major}.{sys.version_info.minor}"
        if args.pyc
        else "source"
    )
    print(f"bundled {len(entries)} files, {total} bytes of {kind}")


if __name__ == "__main__":
    main()
