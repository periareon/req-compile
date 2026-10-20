"""Tests of the entry point that hosts the solver in WebAssembly.

The entry point is plain Python, so it is exercised here natively: a small
in-memory "host" answers its requests the way the Starlark loop does.
"""

# pylint: disable=too-many-lines

import hashlib
import json
from typing import Any, Dict, List, Tuple

import pytest

from req_compile.wasm import entry
from req_compile.wasm import files as wasm_files
from req_compile.wasm import ingest

INDEX = "https://index.example/simple"
MIRROR = "https://mirror.example/simple"

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
            # Served separately or read out of the wheel, the text is the same.
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


def test_failed_download_is_named_for_a_strict_retry() -> None:
    """A page whose download failed is handed back to fetch strictly, not reported missing."""

    class FlakyHost(Host):
        def __init__(self, files: Dict[str, str]) -> None:
            super().__init__(files)
            self.failed = False

        def _answer(self, request: Dict[str, Any]) -> None:
            if (
                request["op"] == "fetch"
                and request["url"].endswith("/b/")
                and not self.failed
            ):
                self.failed = True
                self.facts[request["id"]] = {
                    "error": "download failed: " + request["url"]
                }
                return
            super()._answer(request)

    host = FlakyHost({"/inputs/requirements.in": "a\n"})
    result = host.run(_hub())
    assert result["status"] == "error"
    assert '"b"' in result["message"]
    assert [request["id"] for request in result["retry"]] == ["index:" + INDEX + "/b/"]

    # The host fetches again, drops the error fact and the solve goes on with the document.
    for request in result["retry"]:
        del host.facts[request["id"]]
        host._answer(request)  # pylint: disable=protected-access
    result = host.run(_hub())
    assert result["status"] == "done", result["message"]
    assert set(result["hubs"]["hub"]["locks"]["win_amd64"]["packages"]) == {"a", "b"}


def test_missing_package_names_nothing_to_retry() -> None:
    """A page the index does not have is not fetched again once it was reported missing."""
    host = Host({"/inputs/requirements.in": "nothing-like-this\n"})
    result = host.run(_hub())
    assert result["status"] == "error"
    assert [request["id"] for request in result["retry"]] == [
        "index:" + INDEX + "/nothing-like-this/"
    ], "a 404 is also a failed download: fetched strictly, Bazel reports it with its URL"


def test_ingest_html_index() -> None:
    page = """
    <html><body>
    <a href="../../packages/a-1.0-py3-none-any.whl#sha256=abababababababababababababababababababababababababababababababab" data-requires-python="&gt;=3.8"
       data-core-metadata="sha256=efefefefefefefefefefefefefefefefefefefefefefefefefefefefefefefef">a-1.0-py3-none-any.whl</a><br/>
    <a href="a-0.9.tar.gz" data-yanked="broken">a-0.9.tar.gz</a>
    </body></html>
    """
    fact = entry.ingest_index(f"{INDEX}/a/", page)
    assert fact["files"] == [
        {
            "filename": "a-1.0-py3-none-any.whl",
            "url": "https://index.example/packages/a-1.0-py3-none-any.whl",
            "sha256": "ab" * 32,
            "requires_python": ">=3.8",
            "yanked": False,
            "core_metadata": {"sha256": "ef" * 32},
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


def test_ingest_metadata_keeps_the_fields_the_solver_reads() -> None:
    fact = entry.ingest_metadata(
        "Metadata-Version: 2.2\r\nName: x\r\nVersion: 1.0\r\nSummary: dropped\r\n"
        "Classifier: Programming Language :: Python\r\n"
        'Requires-Dist: y; extra == "all" and\r\n  python_version > "3.8"\r\n'
        "Project-URL: Homepage, https://x.example\r\nDynamic: Requires-Dist\r\n"
        "\r\nBody text\r\n"
    )
    text = (
        "Metadata-Version: 2.2\nName: x\nVersion: 1.0\n"
        'Requires-Dist: y; extra == "all" and python_version > "3.8"\n'
        "Dynamic: Requires-Dist"
    )
    assert fact == {
        "metadata": text,
        "dynamic": ["requires-dist"],
        "metadata_version": "2.2",
        "digest": hashlib.sha256(text.encode()).hexdigest(),
    }
    assert ingest.metadata_fact(text) == fact


def test_metadata_is_recorded_once_per_text() -> None:
    """The texts a solution refers to are returned by digest, shared across platforms."""
    result = Host({"/inputs/requirements.in": "a\n"}).run(_hub())
    assert result["status"] == "done", result
    locks = result["hubs"]["hub"]["locks"]
    digests = {
        package["metadata"]
        for packages in locks.values()
        for package in packages["packages"].values()
    }
    assert digests == set(result["metadata"]), "one text per distinct metadata"
    assert len(digests) == 2, "a and b, each once for both platforms"
    for digest, text in result["metadata"].items():
        assert hashlib.sha256(text.encode()).hexdigest() == digest
        assert "long description" not in text


def test_latin1_round_trip() -> None:
    # pylint: disable=protected-access
    text = "Name: naïve"
    as_starlark_sees_it = text.encode("utf-8").decode("latin-1")
    assert wasm_files.decode_text(as_starlark_sees_it) == text


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

    # Starlark seeds the next evaluation with the files it read and the recorded
    # metadata texts, keyed by digest; the solver joins them to the distributions.
    again = RecordingHost({"/inputs/requirements.in": "a\n"})
    again.facts = {
        key: fact for key, fact in first.facts.items() if key.startswith("file:")
    }
    again.facts.update(
        {"md:" + digest: text for digest, text in solved["metadata"].items()}
    )
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
                    "index": INDEX,
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
                    "index": INDEX,
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


PINNED = """\
# A req-compile style lock, as Dependabot maintains it: version and hashes.
a==1.0 \\
    --hash=sha256:{a}
    # via requirements.in
    # https://files.example/a-1.0-py3-none-any.whl
b==2.0 \\
    --hash=sha256:{b}
    # via a
"""


def test_pinned_hashes_pass_when_they_match() -> None:
    host = Host({"/inputs/requirements.txt": PINNED.format(a="11" * 32, b="22" * 32)})
    result = host.run(_hub(requirements=["/inputs/requirements.txt"]))
    assert result["status"] == "done", result
    packages = result["hubs"]["hub"]["locks"]["win_amd64"]["packages"]
    assert packages["a"]["hash_pinned"] and packages["b"]["hash_pinned"]
    assert packages["a"]["sha256"] == "11" * 32


def test_stale_hash_fails_naming_the_package() -> None:
    # The version of b was bumped, but its hash is the old one.
    host = Host({"/inputs/requirements.txt": PINNED.format(a="11" * 32, b="99" * 32)})
    result = host.run(_hub(requirements=["/inputs/requirements.txt"]))
    assert result["status"] == "error", result
    assert "`b`" in result["message"]
    assert "999999999999" in result["message"]
    assert "b-2.0-py3-none-any.whl" in result["message"]


def test_hashes_are_ignored_when_not_enforced() -> None:
    host = Host({"/inputs/requirements.txt": PINNED.format(a="11" * 32, b="99" * 32)})
    result = host.run(
        _hub(requirements=["/inputs/requirements.txt"], enforce_hashes=False)
    )
    assert result["status"] == "done", result
    assert not result["hubs"]["hub"]["locks"]["win_amd64"]["packages"]["b"][
        "hash_pinned"
    ]


def test_files_without_hashes_are_unaffected() -> None:
    host = Host({"/inputs/requirements.in": "a\n"})
    result = host.run(_hub())
    packages = result["hubs"]["hub"]["locks"]["win_amd64"]["packages"]
    assert not packages["a"]["hash_pinned"]


def test_pinned_hashes_follow_includes() -> None:
    # pylint: disable=protected-access
    hashes = wasm_files.pinned_hashes
    files = {
        "/inputs/requirements.txt": "-r sub/other.txt\n",
        "/inputs/sub/other.txt": "c==3.0 --hash=sha256:ab --hash=sha256:cd  # comment\n",
    }
    host = Host(files)
    host.facts = {"file:" + path: {"text": text} for path, text in files.items()}
    with wasm_files.FactFiles(
        host.facts, wasm_files.Requests()
    ):  # pylint: disable=protected-access
        assert hashes(["/inputs/requirements.txt"]) == {"c": {"ab", "cd"}}


def test_bumped_version_with_old_hash_names_the_new_artifact() -> None:
    # Dependabot bumped b from 1.0 to 2.0 but the hash is still the one of b 1.0,
    # which the index also has, so plain filtering would just find no candidate.
    requirements = "b==2.0 --hash=sha256:" + "55" * 32 + "\n"
    host = Host({"/inputs/requirements.txt": requirements})
    result = host.run(_hub(requirements=["/inputs/requirements.txt"]))
    assert result["status"] == "error", result
    assert "`b`" in result["message"]
    assert "b-2.0-py3-none-any.whl (222222222222)" in result["message"]


def _recorded_b(**extra: Any) -> Dict[str, Any]:
    """A recorded solution holding b 1.0, as Starlark hands it back."""
    recorded = {
        "package": "b",
        "version": "1.0",
        "sha256": "55" * 32,
        "url": "https://files.example/b-1.0-py3-none-any.whl",
        "filename": "b-1.0-py3-none-any.whl",
        "core_metadata": True,
        "deps": [],
        "via": [],
        "index": INDEX,
    }
    recorded.update(extra)
    return {
        "locks": {
            platform: {"b": dict(recorded)}
            for platform in ("manylinux_2_28_x86_64", "win_amd64")
        }
    }


def _b_versions(host: RecordingHost, prior: Dict[str, Any]) -> Tuple[str, List[str]]:
    host.facts["meta:" + "55" * 32] = {
        "metadata": "Name: b\nVersion: 1.0",
        "dynamic": [],
        "metadata_version": "2.1",
    }
    result = host.run(_hub(prior=prior))
    assert result["status"] == "done", result
    version = result["hubs"]["hub"]["locks"]["win_amd64"]["packages"]["b"]["version"]
    return version, [r["url"] for r in host.answered if r["op"] == "fetch"]


def test_recorded_distribution_is_rechecked_against_requires_python() -> None:
    """A recorded wheel for another Python is not reused when the target changes."""
    host = RecordingHost({"/inputs/requirements.in": "b>=1\n"})
    version, fetched = _b_versions(host, _recorded_b(requires_python=">=3.12"))
    assert version == "2.0"
    assert fetched == [f"{INDEX}/b/"]


def test_recorded_distribution_from_a_removed_index_is_fetched_again() -> None:
    host = RecordingHost({"/inputs/requirements.in": "b>=1\n"})
    version, fetched = _b_versions(
        host, _recorded_b(index="https://old.example/simple")
    )
    assert version == "2.0"
    assert fetched == [f"{INDEX}/b/"]


def test_recorded_distribution_answers_only_for_its_index() -> None:
    """With several indexes, only the recorded one stands in; nothing is fetched."""
    host = RecordingHost({"/inputs/requirements.in": "b>=1\n"})
    host.facts["meta:" + "55" * 32] = {
        "metadata": "Name: b\nVersion: 1.0",
        "dynamic": [],
        "metadata_version": "2.1",
    }
    result = host.run(_hub(prior=_recorded_b(), indexes=[MIRROR, INDEX]))
    assert result["status"] == "done", result
    packages = result["hubs"]["hub"]["locks"]["win_amd64"]["packages"]
    assert packages["b"]["version"] == "1.0"
    assert packages["b"]["index"] == INDEX
    assert not [request for request in host.answered if request["op"] == "fetch"]


def test_unpinned_dependency_fails_when_the_file_pins_hashes() -> None:
    """An index cannot add a dependency the pinned file never vouched for."""

    class PoisonedHost(Host):
        def _answer(self, request: Dict[str, Any]) -> None:
            if request["op"] == "metadata" and request["filename"].startswith("a-"):
                body = _metadata("a").replace(
                    "Provides-Extra: fast", "Requires-Dist: c\nProvides-Extra: fast"
                )
                self.documents[request["id"]] = {
                    "kind": "metadata",
                    "url": request["url"],
                    "body": body,
                }
                return
            super()._answer(request)

    host = PoisonedHost(
        {"/inputs/requirements.txt": PINNED.format(a="11" * 32, b="22" * 32)}
    )
    result = host.run(_hub(requirements=["/inputs/requirements.txt"]))
    assert result["status"] == "error", result
    assert "`c`" in result["message"]
    assert "every package must be pinned" in result["message"]


def test_hash_option_separated_by_a_space_is_a_pin() -> None:
    requirements = "b==2.0 --hash sha256:{}\n"
    host = Host({"/inputs/requirements.txt": requirements.format("22" * 32)})
    result = host.run(_hub(requirements=["/inputs/requirements.txt"]))
    assert result["status"] == "done", result
    assert result["hubs"]["hub"]["locks"]["win_amd64"]["packages"]["b"]["hash_pinned"]

    wrong = Host({"/inputs/requirements.txt": requirements.format("99" * 32)})
    result = wrong.run(_hub(requirements=["/inputs/requirements.txt"]))
    assert result["status"] == "error", result
    assert "`b`" in result["message"]


def test_pinned_hashes_follow_tab_separated_includes_and_refuse_other_algorithms() -> (
    None
):
    # pylint: disable=protected-access
    files = {
        "/inputs/requirements.txt": "-r\tsub/other.txt\n",
        "/inputs/sub/other.txt": "c==3.0 --hash=sha256:ab\n",
        "/inputs/md5.txt": "c==3.0 --hash=md5:ab\n",
    }
    facts = {"file:" + path: {"text": text} for path, text in files.items()}
    with wasm_files.FactFiles(facts, wasm_files.Requests()):
        assert wasm_files.pinned_hashes(["/inputs/requirements.txt"]) == {"c": {"ab"}}
        with pytest.raises(wasm_files.RequirementsFileError):
            wasm_files.pinned_hashes(["/inputs/md5.txt"])


def test_file_options_are_refused_unless_they_match_the_hub() -> None:
    # req-compile's own lock files start with the index they were compiled against.
    result = Host({"/inputs/requirements.in": f"--index-url {INDEX}/\na\n"}).run(_hub())
    assert result["status"] == "done", result

    # An index option cannot reorder the search: the primary must be the hub's
    # `index_url`, an extra one of its `extra_index_urls`.
    two = _hub(indexes=[INDEX, MIRROR])
    files = {"/inputs/requirements.in": f"--extra-index-url {MIRROR}\na\n"}
    assert Host(files).run(two)["status"] == "done"
    files = {"/inputs/requirements.in": f"--index-url {MIRROR}\na\n"}
    result = Host(files).run(two)
    assert result["status"] == "error", result
    assert "index_url" in result["message"]

    result = Host(
        {"/inputs/requirements.in": "--index-url https://other.example/simple\na\n"}
    ).run(_hub())
    assert result["status"] == "error", result
    assert "--index-url https://other.example/simple" in result["message"]
    assert "`resolve` tag" in result["message"]

    result = Host({"/inputs/requirements.in": "--no-binary :all:\na\n"}).run(_hub())
    assert result["status"] == "error", result
    assert "--no-binary" in result["message"]


def test_constraint_files_named_in_requirements_apply() -> None:
    files = {
        "/inputs/requirements.in": "-c constraints.txt\na\n",
        "/inputs/constraints.txt": "b<2\n",
    }
    result = Host(files).run(_hub())
    assert result["status"] == "error", result  # the index only has b 2.0
    assert '"b' in result["message"] or "`b`" in result["message"]

    files["/inputs/constraints.txt"] = "b>=2\n"
    result = Host(files).run(_hub())
    assert result["status"] == "done", result
    # Every file read is reported, so that Bazel watches the included ones too.
    assert result["hubs"]["hub"]["files"] == [
        "/inputs/constraints.txt",
        "/inputs/requirements.in",
    ]


def test_hashless_index_entry_is_pinned_by_its_download() -> None:
    class HashlessHost(Host):
        def _answer(self, request: Dict[str, Any]) -> None:
            if request["op"] == "fetch" and request["url"].endswith("/b/"):
                page = json.loads(_page("b"))
                for item in page["files"]:
                    item.pop("hashes", None)
                self.documents[request["id"]] = {
                    "kind": "index",
                    "url": request["url"],
                    "body": json.dumps(page),
                }
                return
            if request["op"] == "metadata" and request["filename"].startswith("b-"):
                assert request["core_metadata"] is False, "the file itself is fetched"
                self.documents[request["id"]] = {
                    "kind": "metadata",
                    "url": request["url"],
                    "body": _metadata("b"),
                    "sha256": "66" * 32,
                }
                return
            super()._answer(request)

    result = HashlessHost({"/inputs/requirements.in": "b\n"}).run(_hub())
    assert result["status"] == "done", result
    assert result["hubs"]["hub"]["locks"]["win_amd64"]["packages"]["b"]["sha256"] == (
        "66" * 32
    )


def test_failed_metadata_download_is_named_for_a_strict_retry() -> None:
    class FlakyMetadataHost(Host):
        failed = False

        def _answer(self, request: Dict[str, Any]) -> None:
            if (
                request["op"] == "metadata"
                and request["filename"].startswith("b-")
                and not self.failed
            ):
                self.failed = True
                self.facts[request["id"]] = {
                    "error": "download failed: " + request["url"]
                }
                return
            super()._answer(request)

    host = FlakyMetadataHost({"/inputs/requirements.in": "b\n"})
    result = host.run(_hub())
    assert result["status"] == "error", result
    assert [request["op"] for request in result["retry"]] == ["metadata"]

    for request in result["retry"]:
        del host.facts[request["id"]]
        host._answer(request)  # pylint: disable=protected-access
    result = host.run(_hub())
    assert result["status"] == "done", result["message"]


def test_hash_mismatch_on_one_index_does_not_end_the_search() -> None:
    class TwoIndexHost(Host):
        def _answer(self, request: Dict[str, Any]) -> None:
            if request["op"] == "fetch" and request["url"].startswith(MIRROR):
                if request["url"].endswith("/b/"):
                    page = json.loads(_page("b"))
                    wheel = page["files"][0]
                    wheel["hashes"]["sha256"] = "66" * 32
                    wheel["url"] = "https://mirror.example/files/" + wheel["filename"]
                    self.documents[request["id"]] = {
                        "kind": "index",
                        "url": request["url"],
                        "body": json.dumps(page),
                    }
                else:
                    self.facts[request["id"]] = {"error": "404"}
                return
            super()._answer(request)

    requirements = "b==2.0 --hash=sha256:" + "66" * 32 + "\n"
    host = TwoIndexHost({"/inputs/requirements.txt": requirements})
    result = host.run(
        _hub(requirements=["/inputs/requirements.txt"], indexes=[INDEX, MIRROR])
    )
    assert result["status"] == "done", result
    packages = result["hubs"]["hub"]["locks"]["win_amd64"]["packages"]
    assert packages["b"]["sha256"] == "66" * 32
    assert packages["b"]["index"] == MIRROR

    # When no index matches, the mismatch is what gets reported.
    nowhere = TwoIndexHost(
        {"/inputs/requirements.txt": "b==2.0 --hash=sha256:" + "77" * 32 + "\n"}
    )
    result = nowhere.run(
        _hub(requirements=["/inputs/requirements.txt"], indexes=[INDEX, MIRROR])
    )
    assert result["status"] == "error", result
    assert "222222222222" in result["message"] and "666666666666" in result["message"]


def test_pinned_files_read_metadata_from_the_wheel_itself() -> None:
    """With hashes pinned, metadata comes from the pinned bytes, not an index's sidecar."""
    pinned = RecordingHost(
        {"/inputs/requirements.txt": PINNED.format(a="11" * 32, b="22" * 32)}
    )
    assert (
        pinned.run(_hub(requirements=["/inputs/requirements.txt"]))["status"] == "done"
    )
    metadata = [r for r in pinned.answered if r["op"] == "metadata"]
    assert metadata and all(r["core_metadata"] is False for r in metadata)

    # Without pins the sidecar, vouched for by its own hash, is used.
    plain = RecordingHost({"/inputs/requirements.in": "a\n"})
    assert plain.run(_hub())["status"] == "done"
    metadata = [r for r in plain.answered if r["op"] == "metadata"]
    assert metadata and all(
        r["core_metadata"] == {"sha256": "ab" * 32} for r in metadata
    )


def test_sidecar_without_a_hash_is_never_fetched() -> None:
    class BareSidecarHost(RecordingHost):
        def _answer(self, request: Dict[str, Any]) -> None:
            if request["op"] == "fetch" and request["url"].endswith("/b/"):
                page = json.loads(_page("b"))
                page["files"][0]["core-metadata"] = True
                self.documents[request["id"]] = {
                    "kind": "index",
                    "url": request["url"],
                    "body": json.dumps(page),
                }
                return
            super()._answer(request)

    host = BareSidecarHost({"/inputs/requirements.in": "b\n"})
    assert host.run(_hub())["status"] == "done"
    assert [r["core_metadata"] for r in host.answered if r["op"] == "metadata"] == [
        False
    ]


def test_dynamic_fields_may_share_a_line() -> None:
    fact = ingest.metadata_fact(
        "Metadata-Version: 2.2\nName: x\nDynamic: Requires-Dist, Provides-Extra"
    )
    assert fact["dynamic"] == ["requires-dist", "provides-extra"]


def test_index_fragments_with_several_hashes() -> None:
    page = entry.ingest_index(
        f"{INDEX}/a/",
        '<a href="../../p/a-1.0-py3-none-any.whl#sha256='
        + "11" * 32
        + "&md5="
        + "22" * 16
        + '">'
        "a-1.0-py3-none-any.whl</a>"
        '<a href="../../p/a-1.1-py3-none-any.whl#sha256=short">a-1.1-py3-none-any.whl</a>',
    )
    assert [f["sha256"] for f in page["files"]] == ["11" * 32, ""]
    assert page["files"][0]["url"].endswith("/p/a-1.0-py3-none-any.whl")


def test_hash_after_a_commented_continuation_is_a_pin() -> None:
    files = {
        "/inputs/requirements.txt": "c==3.0 \\  # pinned by the bot\n    --hash=sha256:ab\n"
    }
    facts = {"file:" + path: {"text": text} for path, text in files.items()}
    with wasm_files.FactFiles(facts, wasm_files.Requests()):
        assert wasm_files.pinned_hashes(["/inputs/requirements.txt"]) == {"c": {"ab"}}


def test_pinned_requirements_file_pins_what_it_lists_and_allows_the_rest() -> None:
    """The hub's requirements.txt pins, with hashes, the packages in it while the
    requirements allow their versions; a package it does not list yet, added to
    requirements.in, resolves freely."""
    files = {
        "/inputs/requirements.in": "a\n",
        "/inputs/requirements.txt": "b==2.0 \\\n    --hash=sha256:" + "22" * 32 + "\n",
    }
    result = Host(files).run(_hub(pins="/inputs/requirements.txt"))
    assert result["status"] == "done", result
    packages = result["hubs"]["hub"]["locks"]["win_amd64"]["packages"]
    assert packages["b"]["hash_pinned"] and not packages["a"]["hash_pinned"]
    assert result["hubs"]["hub"]["files"] == [
        "/inputs/requirements.in",
        "/inputs/requirements.txt",
    ]

    # A bumped pin whose hash is wrong fails naming the package.
    files["/inputs/requirements.txt"] = "b==2.0 --hash=sha256:" + "99" * 32 + "\n"
    result = Host(files).run(_hub(pins="/inputs/requirements.txt"))
    assert result["status"] == "error", result
    assert "`b`" in result["message"]


class _TwoVersionsOfB(Host):
    """An index with b 1.0 (sha 55) beside b 2.0, each with its own metadata."""

    def _answer(self, request: Dict[str, Any]) -> None:
        if request["op"] == "fetch" and request["url"].endswith("/b/"):
            page = json.loads(_page("b"))
            page["files"].append(
                {
                    "filename": "b-1.0-py3-none-any.whl",
                    "url": "https://files.example/b-1.0-py3-none-any.whl",
                    "hashes": {"sha256": "55" * 32},
                    "requires-python": ">=3.8",
                    "yanked": False,
                    "core-metadata": {"sha256": "cd" * 32},
                }
            )
            self.documents[request["id"]] = {
                "kind": "index",
                "url": request["url"],
                "body": json.dumps(page),
            }
            return
        if (
            request["op"] == "metadata"
            and request["filename"] == "b-1.0-py3-none-any.whl"
        ):
            self.documents[request["id"]] = {
                "kind": "metadata",
                "url": request["url"],
                "body": "Metadata-Version: 2.1\nName: b\nVersion: 1.0\n",
            }
            return
        super()._answer(request)


def test_pinned_file_version_yields_to_the_requirements() -> None:
    """Like pip-compile with an existing lock: a pin the requirements no longer
    allow is dropped and the package resolved again, with no `--upgrade` needed;
    its stale hash then binds nothing."""
    files = {
        "/inputs/requirements.in": "b>=2\n",
        "/inputs/requirements.txt": "b==1.0 --hash=sha256:" + "55" * 32 + "\n",
    }
    result = _TwoVersionsOfB(files).run(_hub(pins="/inputs/requirements.txt"))
    assert result["status"] == "done", result
    b = result["hubs"]["hub"]["locks"]["win_amd64"]["packages"]["b"]
    assert b["version"] == "2.0"
    assert not b["hash_pinned"], "the file vouched for 1.0 only"

    # Even a wrong hash on the dropped pin is moot: the version is out anyway.
    files["/inputs/requirements.txt"] = "b==1.0 --hash=sha256:" + "99" * 32 + "\n"
    result = _TwoVersionsOfB(files).run(_hub(pins="/inputs/requirements.txt"))
    assert result["status"] == "done", result
    assert (
        result["hubs"]["hub"]["locks"]["win_amd64"]["packages"]["b"]["version"] == "2.0"
    )

    # While the requirements allow the pinned version, it is kept and its hash binds.
    files["/inputs/requirements.in"] = "b\n"
    result = _TwoVersionsOfB(files).run(_hub(pins="/inputs/requirements.txt"))
    assert result["status"] == "error", result
    assert "`b`" in result["message"] and "1.0" in result["message"]


def test_pinned_file_bump_outranks_the_recorded_solution() -> None:
    """Dependabot bumps the file; the lock still records the old version. The
    file wins and the page is fetched to find the new version."""
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
                    "index": INDEX,
                },
            }
            for platform in ("manylinux_2_28_x86_64", "win_amd64")
        }
    }
    files = {
        "/inputs/requirements.in": "b\n",
        "/inputs/requirements.txt": "b==2.0 --hash=sha256:" + "22" * 32 + "\n",
    }
    host = _TwoVersionsOfB(files)
    host.facts["meta:" + "55" * 32] = {
        "metadata": "Name: b\nVersion: 1.0",
        "dynamic": [],
        "metadata_version": "2.1",
    }
    result = host.run(_hub(pins="/inputs/requirements.txt", prior=prior))
    assert result["status"] == "done", result
    b = result["hubs"]["hub"]["locks"]["win_amd64"]["packages"]["b"]
    assert b["version"] == "2.0" and b["hash_pinned"]

    # The recorded version stands while the file still pins it, without a fetch.
    files["/inputs/requirements.txt"] = "b==1.0 --hash=sha256:" + "55" * 32 + "\n"
    kept = RecordingHost(files)
    kept.facts["meta:" + "55" * 32] = host.facts["meta:" + "55" * 32]
    result = kept.run(_hub(pins="/inputs/requirements.txt", prior=prior))
    assert result["status"] == "done", result
    assert (
        result["hubs"]["hub"]["locks"]["win_amd64"]["packages"]["b"]["version"] == "1.0"
    )
    assert not [r for r in kept.answered if r["op"] == "fetch"]


def test_upgrade_lifts_the_pinned_file_for_the_named_packages() -> None:
    """`REQ_COMPILE_UPGRADE` is how a pin in the hub's file is moved on purpose."""
    files = {
        "/inputs/requirements.in": "b\n",
        "/inputs/requirements.txt": "b==1.0 --hash=sha256:" + "55" * 32 + "\n",
    }

    def version(**extra: Any) -> str:
        result = _TwoVersionsOfB(files).run(
            _hub(pins="/inputs/requirements.txt"), **extra
        )
        assert result["status"] == "done", result
        return result["hubs"]["hub"]["locks"]["win_amd64"]["packages"]["b"]["version"]

    assert version() == "1.0", "the file pins b"
    assert version(upgrade=["b"]) == "2.0", "naming b lifts its pin and hash"
    assert version(upgrade="all") == "2.0"
    assert version(upgrade=["a"]) == "1.0", "another package's upgrade leaves b pinned"
