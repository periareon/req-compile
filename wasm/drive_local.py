#!/usr/bin/env python3
"""Drive the solver module in rounds from the host, the way the Starlark loop will.

Usage: drive_local.py MODULE.wasm requirements.in [--platform TAG]... [--python 3.11]

Every request the solver returns is satisfied here: files are read from disk,
index pages and metadata are downloaded, documents are passed back through the
module's `ingest` operation, and the solver is called again with all the facts.
This is the reference for the Starlark implementation and a way to measure it.
"""

import argparse
import hashlib
import io
import json
import os
import ssl
import sys
import tarfile
import time
import urllib.request
import zipfile

from run_local import execute

INPUT_ROOT = "/inputs"


def call(module, payload):
    code, output = execute(module, "solve", json.dumps(payload).encode("utf-8"))
    result = json.loads(output.decode("utf-8"))
    if code != 0:
        raise SystemExit(
            f"solver returned {code}: {json.dumps(result, indent=2)[:4000]}"
        )
    if result.get("log"):
        print(result["log"], file=sys.stderr)
    return result


def _ssl_context():
    try:
        import certifi  # pylint: disable=import-outside-toplevel
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


def fetch(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, context=_ssl_context()) as response:
        return response.read()


def metadata_text(request):
    """The core metadata of a distribution, as the Starlark side would obtain it.

    Returns the metadata, how it was obtained and, when the whole file was
    fetched, its sha256, which pins a distribution the index gave no hash for.
    """
    url = request["url"]
    if request["core_metadata"]:
        return fetch(url + ".metadata"), "served", None
    data = fetch(url)
    sha256 = hashlib.sha256(data).hexdigest()
    if request["kind"] == "wheel":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for name in archive.namelist():
                if name.endswith(".dist-info/METADATA") and name.count("/") == 1:
                    return archive.read(name), "wheel", sha256
    elif url.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for name in archive.namelist():
                if name.endswith("/PKG-INFO") and name.count("/") == 1:
                    return archive.read(name), "sdist", sha256
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
            for member in archive.getmembers():
                if member.name.endswith("/PKG-INFO") and member.name.count("/") == 1:
                    handle = archive.extractfile(member)
                    if handle is not None:
                        return handle.read(), "sdist", sha256
    raise RuntimeError(f"no metadata for {url}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("module")
    parser.add_argument("requirements")
    parser.add_argument("--platform", action="append", default=[])
    parser.add_argument("--python", default="3.11")
    parser.add_argument("--index", default="https://pypi.org/simple")
    parser.add_argument("--allow-sdists", action="store_true")
    parser.add_argument("--max-rounds", type=int, default=50)
    parser.add_argument("--dump", help="write the final solve input to this file")
    parser.add_argument(
        "--prior", help="a requirements.txt whose pins the solver starts from"
    )
    args = parser.parse_args()

    requirements_dir = os.path.dirname(os.path.abspath(args.requirements))
    files = {
        INPUT_ROOT
        + "/"
        + os.path.basename(args.requirements): os.path.abspath(args.requirements)
    }

    hubs = {
        "demo": {
            "python_version": args.python,
            "platforms": args.platform or ["manylinux_2_28_x86_64"],
            "requirements": [INPUT_ROOT + "/" + os.path.basename(args.requirements)],
            "constraints": [],
            "indexes": [args.index],
            "allow_sdists": args.allow_sdists,
            "allow_prerelease": False,
        }
    }
    if args.prior:
        prior = {}
        with open(args.prior) as handle:
            for line in handle:
                line = line.strip()
                if "==" in line and not line.startswith("#"):
                    name, _, version = line.partition("==")
                    prior[name.strip()] = version.strip(" \\")
        hubs["demo"]["prior"] = prior
    facts = {}
    documents = {}
    started = time.monotonic()
    for round_number in range(1, args.max_rounds + 1):
        payload = {"op": "solve", "hubs": hubs, "facts": facts, "documents": documents}
        if args.dump:
            with open(args.dump, "w") as handle:
                json.dump(payload, handle)
        result = call(args.module, payload)
        facts.update(result.get("facts", {}))
        documents = {}
        if result["status"] == "done":
            print(
                f"solved in {round_number - 1} rounds, {time.monotonic() - started:.1f}s",
                file=sys.stderr,
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            return
        if result["status"] == "error":
            raise SystemExit(f"resolution failed: {result['message']}")

        requests = result["requests"]
        kinds = {}
        for request in requests:
            kinds[request["op"]] = kinds.get(request["op"], 0) + 1
        print(
            f"round {round_number}: {len(requests)} requests {kinds}", file=sys.stderr
        )
        for request in requests:
            if request["op"] == "read":
                path = files.get(request["path"]) or os.path.join(
                    requirements_dir, os.path.relpath(request["path"], INPUT_ROOT)
                )
                try:
                    with open(path, "rb") as handle:
                        facts[request["id"]] = {"text": handle.read().decode("latin-1")}
                except OSError as ex:
                    facts[request["id"]] = {"error": str(ex)}
            elif request["op"] == "fetch":
                try:
                    body = fetch(request["url"], request.get("headers"))
                    documents[request["id"]] = {
                        "kind": request["ingest"],
                        "url": request["url"],
                        "body": body.decode("latin-1"),
                    }
                except Exception as ex:  # pylint: disable=broad-except
                    facts[request["id"]] = {"error": str(ex)}
            elif request["op"] == "metadata":
                try:
                    body, how, sha256 = metadata_text(request)
                    documents[request["id"]] = {
                        "kind": "metadata",
                        "url": request["url"],
                        "body": body.decode("latin-1"),
                    }
                    if sha256:
                        documents[request["id"]]["sha256"] = sha256
                except Exception as ex:  # pylint: disable=broad-except
                    facts[request["id"]] = {"error": str(ex)}
            else:
                raise SystemExit(f"unknown request {request}")
    raise SystemExit("did not converge")


if __name__ == "__main__":
    main()
