"""Tests of the entry point that hosts the solver in WebAssembly.

The entry point is plain Python, so it is exercised here natively: a small
in-memory "host" answers its requests the way the Starlark loop does.
"""

import json
from typing import Any, Dict, List

import pytest

from req_compile.wasm import entry

INDEX = "https://index.example/simple"

WHEELS = {
    "a": ("a-1.0-py3-none-any.whl", "11" * 32, ["b>=1", "c; extra == 'fast'"]),
    "b": ("b-2.0-py3-none-any.whl", "22" * 32, []),
    "c": ("c-3.0-py3-none-any.whl", "33" * 32, []),
}


def _page(name: str) -> str:
    filename, sha256, _ = WHEELS[name]
    return json.dumps(
        {
            "name": name,
            "files": [
                {
                    "filename": filename,
                    "url": f"https://files.example/{filename}",
                    "hashes": {"sha256": sha256},
                    "requires-python": ">=3.8",
                    "yanked": False,
                    "core-metadata": {"sha256": "ab" * 32},
                },
                {
                    "filename": f"{name}-0.1.tar.gz",
                    "url": f"https://files.example/{name}-0.1.tar.gz",
                    "hashes": {"sha256": "44" * 32},
                    "core-metadata": False,
                },
            ],
        }
    )


def _metadata(name: str) -> str:
    _, _, requires = WHEELS[name]
    lines = [
        "Metadata-Version: 2.1",
        f"Name: {name}",
        f"Version: {WHEELS[name][0].split('-')[1]}",
    ]
    lines += [f"Requires-Dist: {req}" for req in requires]
    lines += [
        "Provides-Extra: fast",
        "",
        "The long description, which the solver never needs.",
    ]
    return "\n".join(lines)


class Host:
    """Answers the solver's requests from canned data, like the Starlark loop would."""

    def __init__(self, files: Dict[str, str]) -> None:
        self.files = files
        self.facts: Dict[str, Any] = {}
        self.documents: Dict[str, Any] = {}
        self.rounds = 0

    def run(
        self, hubs: Dict[str, Any], max_rounds: int = 10, **extra: Any
    ) -> Dict[str, Any]:
        for _ in range(max_rounds):
            self.rounds += 1
            payload = {
                "op": "solve",
                "hubs": hubs,
                "facts": self.facts,
                "documents": self.documents,
            }
            payload.update(extra)
            output, code = entry.main(json.dumps(payload).encode("utf-8"))
            assert code == 0, output
            result = json.loads(output)
            self.facts.update(result.get("facts", {}))
            self.documents = {}
            if result["status"] != "need":
                return result
            for request in result["requests"]:
                self._answer(request)
        raise AssertionError("did not converge")

    def _answer(self, request: Dict[str, Any]) -> None:
        if request["op"] == "read":
            self.facts[request["id"]] = {"text": self.files[request["path"]]}
        elif request["op"] == "fetch":
            name = request["url"].rstrip("/").rsplit("/", 1)[1]
            body = _page(name) if name in WHEELS else ""
            if body:
                self.documents[request["id"]] = {
                    "kind": "index",
                    "url": request["url"],
                    "body": body,
                }
            else:
                self.facts[request["id"]] = {"error": "404"}
        elif request["op"] == "metadata":
            assert request["core_metadata"], "wheels advertise served metadata"
            name = request["filename"].split("-")[0]
            self.documents[request["id"]] = {
                "kind": "metadata",
                "url": request["url"],
                "body": _metadata(name),
            }
        else:
            raise AssertionError(request)


def _hub(**overrides: Any) -> Dict[str, Any]:
    hub = {
        "python_version": "3.11",
        "platforms": ["manylinux_2_28_x86_64", "win_amd64"],
        "requirements": ["/inputs/requirements.in"],
        "constraints": [],
        "indexes": [INDEX],
        "allow_sdists": False,
        "allow_prerelease": False,
    }
    hub.update(overrides)
    return {"hub": hub}


def test_solve_in_rounds() -> None:
    host = Host({"/inputs/requirements.in": "a\n"})
    result = host.run(_hub())
    assert result["status"] == "done", result
    locks = result["hubs"]["hub"]["locks"]
    assert set(locks) == {"manylinux_2_28_x86_64", "win_amd64"}
    packages = locks["win_amd64"]["packages"]
    assert set(packages) == {"a", "b"}, "the extra of a is not requested"
    assert packages["a"]["version"] == "1.0"
    assert packages["a"]["sha256"] == "11" * 32
    assert packages["a"]["url"] == "https://files.example/a-1.0-py3-none-any.whl"
    assert packages["a"]["deps"] == ["b"]
    assert packages["a"]["via"] == ["/inputs/requirements.in"]
    assert packages["b"]["via"] == ["a"]
    # Read the file, fetch the page, fetch the metadata, then one level of
    # dependencies per two rounds, plus the final call.
    assert host.rounds <= 6
    assert set(result["consulted"]) == {"11" * 32, "22" * 32}


def test_includes_and_extras() -> None:
    host = Host(
        {
            "/inputs/requirements.in": "-r other.in\n",
            "/inputs/other.in": "a[fast]\n",
        }
    )
    result = host.run(_hub())
    assert result["status"] == "done", result
    packages = result["hubs"]["hub"]["locks"]["manylinux_2_28_x86_64"]["packages"]
    assert set(packages) == {"a", "b", "c"}
    assert packages["a"]["deps"] == ["b", "c"]
    # Includes are flattened into the file that was asked for, as on the command line.
    assert packages["a"]["via"] == ["/inputs/requirements.in"]


def test_prior_pins_are_lazy() -> None:
    host = Host({"/inputs/requirements.in": "a\n"})
    result = host.run(_hub(prior={"b": "1.5"}))
    assert result["status"] == "done", result
    # Nothing on the index is called 1.5, so the pin is dropped rather than failing.
    assert (
        result["hubs"]["hub"]["locks"]["win_amd64"]["packages"]["b"]["version"] == "2.0"
    )


def test_missing_package_is_an_error() -> None:
    host = Host({"/inputs/requirements.in": "nothing-like-this\n"})
    result = host.run(_hub())
    assert result["status"] == "error"
    assert "nothing-like-this" in result["message"]


def test_ingest_html_index() -> None:
    page = """
    <html><body>
    <a href="../../packages/a-1.0-py3-none-any.whl#sha256=abcd" data-requires-python="&gt;=3.8"
       data-core-metadata="sha256=ef01">a-1.0-py3-none-any.whl</a><br/>
    <a href="a-0.9.tar.gz" data-yanked="broken">a-0.9.tar.gz</a>
    </body></html>
    """
    fact = entry.ingest_index(f"{INDEX}/a/", page)
    assert fact["files"] == [
        {
            "filename": "a-1.0-py3-none-any.whl",
            "url": "https://index.example/packages/a-1.0-py3-none-any.whl",
            "sha256": "abcd",
            "requires_python": ">=3.8",
            "yanked": False,
            "core_metadata": {"sha256": "ef01"},
        },
        {
            "filename": "a-0.9.tar.gz",
            "url": f"{INDEX}/a/a-0.9.tar.gz",
            "sha256": "",
            "requires_python": "",
            "yanked": True,
            "core_metadata": False,
        },
    ]


def test_ingest_metadata_keeps_the_header() -> None:
    fact = entry.ingest_metadata(
        "Metadata-Version: 2.2\r\nName: x\r\nDynamic: Requires-Dist\r\n\r\nBody text\r\n"
    )
    assert fact == {
        "metadata": "Metadata-Version: 2.2\nName: x\nDynamic: Requires-Dist",
        "dynamic": ["requires-dist"],
        "metadata_version": "2.2",
    }


def test_latin1_round_trip() -> None:
    # pylint: disable=protected-access
    text = "Name: naïve"
    as_starlark_sees_it = text.encode("utf-8").decode("latin-1")
    assert entry._decode(as_starlark_sees_it) == text


@pytest.mark.parametrize("op", ["ping"])
def test_ping(op: str) -> None:
    output, code = entry.main(json.dumps({"op": op, "echo": 1}).encode("utf-8"))
    assert code == 0
    assert json.loads(output)["echo"] == 1


def _prior_from(result: Dict[str, Any]) -> Dict[str, Any]:
    """The recorded solution Starlark would hand back, built from a `done` result."""
    return {
        "locks": {
            platform: lock["packages"]
            for platform, lock in result["hubs"]["hub"]["locks"].items()
        }
    }


class RecordingHost(Host):
    """A host that remembers which requests it answered."""

    def __init__(self, files: Dict[str, str]) -> None:
        super().__init__(files)
        self.answered: List[Dict[str, Any]] = []

    def _answer(self, request: Dict[str, Any]) -> None:
        self.answered.append(request)
        super()._answer(request)


def test_prior_solution_needs_no_requests() -> None:
    first = Host({"/inputs/requirements.in": "a\n"})
    solved = first.run(_hub())

    # Starlark seeds the next evaluation with the files it read and the recorded metadata.
    again = RecordingHost({"/inputs/requirements.in": "a\n"})
    again.facts = {
        key: fact
        for key, fact in first.facts.items()
        if key.startswith(("file:", "meta:"))
    }
    result = again.run(_hub(prior=_prior_from(solved)))
    assert result["status"] == "done", result
    assert again.rounds == 1
    assert not again.answered
    assert result["hubs"] == solved["hubs"]


def test_prior_pin_is_dropped_when_it_conflicts() -> None:
    # The recorded b is 1.0, which the new requirement rejects, so its real page is fetched.
    prior = {
        "locks": {
            platform: {
                "b": {
                    "package": "b",
                    "version": "1.0",
                    "sha256": "55" * 32,
                    "url": "https://files.example/b-1.0-py3-none-any.whl",
                    "filename": "b-1.0-py3-none-any.whl",
                    "core_metadata": True,
                    "deps": [],
                    "via": [],
                },
            }
            for platform in ("manylinux_2_28_x86_64", "win_amd64")
        }
    }
    host = RecordingHost({"/inputs/requirements.in": "b>=2\n"})
    host.facts["meta:" + "55" * 32] = {
        "metadata": "Name: b\nVersion: 1.0",
        "dynamic": [],
        "metadata_version": "2.1",
    }
    result = host.run(_hub(prior=prior))
    assert result["status"] == "done", result
    assert (
        result["hubs"]["hub"]["locks"]["win_amd64"]["packages"]["b"]["version"] == "2.0"
    )
    assert [r["url"] for r in host.answered if r["op"] == "fetch"] == [f"{INDEX}/b/"]


def test_prior_pin_kept_without_a_fetch() -> None:
    prior = {
        "locks": {
            platform: {
                "b": {
                    "package": "b",
                    "version": "1.0",
                    "sha256": "55" * 32,
                    "url": "https://files.example/b-1.0-py3-none-any.whl",
                    "filename": "b-1.0-py3-none-any.whl",
                    "core_metadata": True,
                    "deps": [],
                    "via": [],
                },
            }
            for platform in ("manylinux_2_28_x86_64", "win_amd64")
        }
    }
    files = {"/inputs/requirements.in": "b>=1\n"}
    kept = RecordingHost(files)
    kept.facts["meta:" + "55" * 32] = {
        "metadata": "Name: b\nVersion: 1.0",
        "dynamic": [],
        "metadata_version": "2.1",
    }
    result = kept.run(_hub(prior=prior))
    assert (
        result["hubs"]["hub"]["locks"]["win_amd64"]["packages"]["b"]["version"] == "1.0"
    )
    assert not [r for r in kept.answered if r["op"] == "fetch"]

    # Upgrading ignores the recorded solution and finds the newer b on the index.
    upgraded = RecordingHost(files)
    result = upgraded.run(_hub(prior=prior), upgrade="all")
    assert (
        result["hubs"]["hub"]["locks"]["win_amd64"]["packages"]["b"]["version"] == "2.0"
    )

    # So does naming the package.
    named = RecordingHost(files)
    result = named.run(_hub(prior=prior), upgrade=["b"])
    assert (
        result["hubs"]["hub"]["locks"]["win_amd64"]["packages"]["b"]["version"] == "2.0"
    )
