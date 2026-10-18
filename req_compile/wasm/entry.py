"""Entry point of the solver when it runs inside Bazel's `execute_wasm`.

The module cannot perform any I/O, so this adapts the solver to facts: a
dictionary of everything Bazel has read or downloaded so far, keyed by what it
is. A `Repository` serves candidates and metadata from the facts and raises
`NeedFacts` the first time something is missing, which ends the round. The
requests collected on the way, plus speculative ones for facts the next rounds
will evidently need, are returned to Starlark, which fetches them and calls
again with the larger set of facts. The solver itself, `perform_compile_group`,
is the one the command line uses.

A hub may come with a prior solution, recorded in the lock file by an earlier
evaluation. Its versions are soft pins, so packages the new requirements do not
disturb keep their versions, and its distributions stand in for index pages: a
package whose recorded version still satisfies every requirement never has its
index page fetched again.

Three operations share the single exported function:

- `ingest` turns a raw document (an index page or a metadata file) into the
  compact fact Starlark keeps.
- `solve` resolves every hub of the input against the facts.
- `ping` reports the interpreter, for smoke tests.
"""

import builtins
import io
import json
import logging
import os
import sys
import traceback
import urllib.parse
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import packaging.requirements
import packaging.version

from req_compile import utils
from req_compile.compile import AllOnlyBinarySet, perform_compile_group
from req_compile.containers import RequirementContainer, RequirementsFile
from req_compile.dists import DistributionCollection
from req_compile.errors import (
    MetadataError,
    NoCandidateException,
    NoCommonVersionException,
)
from req_compile.metadata.dist_info import _parse_flat_metadata
from req_compile.repos.multi import MultiRepository
from req_compile.repos.pypi import check_python_compatibility, normalize
from req_compile.repos.repository import (
    Candidate,
    DistributionType,
    Repository,
    filename_to_candidate,
    filter_candidates,
    sort_candidates,
)
from req_compile.target import TargetEnvironment
from req_compile.utils import NormName

# Requirement files are addressed by paths under this root; Starlark maps them to labels.
INPUT_ROOT = "/inputs"

ACCEPT_INDEX = "application/vnd.pypi.simple.v1+json, text/html;q=0.1"

LOG = logging.getLogger("req_compile.wasm")


class NeedFacts(Exception):
    """A fact the solver needs is missing; the round is over."""


class HashMismatch(Exception):
    """No artifact of a project matches the hashes its requirement file pins."""

    def __init__(self, name: str, pinned: Set[str], found: Dict[str, str]) -> None:
        super().__init__(name)
        self.name = name
        self.pinned = pinned
        self.found = found

    def __str__(self) -> str:
        available = ", ".join(
            "{} ({})".format(filename, sha256[:12])
            for filename, sha256 in sorted(self.found.items())
        )
        return (
            "No artifact of `{}` on the index matches the --hash values pinned for it "
            "({}). The index offers: {}. Update the hashes along with the version, or "
            "set `enforce_hashes = False`."
        ).format(
            self.name,
            ", ".join(sorted(value[:12] for value in self.pinned)),
            available or "nothing",
        )


_HASH_OPTION = "--hash=sha256:"


def pinned_hashes(paths: Iterable[str]) -> Dict[NormName, Set[str]]:
    """The `--hash` values the requirement files pin, by project.

    Follows `-r` includes like req-compile does. Files are read through `open()`,
    so this must run while `_FactFiles` is installed.
    """
    result: Dict[NormName, Set[str]] = {}
    seen: Set[str] = set()

    def visit(path: str) -> None:
        if path in seen:
            return
        seen.add(path)
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        logical = ""
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.endswith("\\"):
                logical += line[:-1] + " "
                continue
            text, logical = (logical + line).strip(), ""
            if text.startswith(("-r ", "--requirement ")):
                include = text.split(None, 1)[1].strip()
                visit(os.path.join(os.path.dirname(path), include))
                continue
            if text.startswith("-"):
                continue
            comment = text.find(" #")
            if comment != -1:
                text = text[:comment]
            parts = text.split()
            hashes = {
                part[len(_HASH_OPTION) :]
                for part in parts
                if part.startswith(_HASH_OPTION)
            }
            if not hashes:
                continue
            try:
                req = utils.parse_requirement(
                    " ".join(part for part in parts if not part.startswith("--"))
                )
            except ValueError:
                continue
            if req is not None:
                result.setdefault(utils.normalize_project_name(req.name), set()).update(
                    hashes
                )

    for path in paths:
        visit(path)
    return result


class Requests:
    """The facts to obtain before the next round, deduplicated by id."""

    def __init__(self) -> None:
        self.by_id: Dict[str, Dict[str, Any]] = {}

    def add(self, request: Dict[str, Any]) -> None:
        self.by_id.setdefault(request["id"], request)

    def as_list(self) -> List[Dict[str, Any]]:
        return [self.by_id[key] for key in sorted(self.by_id)]


def _decode(value: str) -> str:
    """Recover text that Starlark read as ISO-8859-1 and JSON encoded as is."""
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


class _IndexHTMLParser(HTMLParser):
    """Collect the file entries of a PEP 503 page, PEP 658/714 attributes included."""

    def __init__(self, page_url: str) -> None:
        super().__init__()
        self.page_url = page_url
        self.files: List[Dict[str, Any]] = []
        self._current: Optional[Dict[str, Any]] = None

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag != "a":
            return
        attributes = dict(attrs)
        href = attributes.get("href")
        if not href:
            return
        self._current = _file_entry(
            self.page_url,
            href,
            requires_python=attributes.get("data-requires-python"),
            yanked="data-yanked" in attributes,
            core_metadata=attributes.get(
                "data-core-metadata", attributes.get("data-dist-info-metadata")
            ),
        )

    def handle_data(self, data: str) -> None:
        if self._current is not None and data.strip():
            self._current["filename"] = data.strip()
            self.files.append(self._current)
            self._current = None

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._current = None


def _file_entry(
    page_url: str,
    href: str,
    requires_python: Optional[str],
    yanked: Any,
    core_metadata: Any,
    sha256: Optional[str] = None,
) -> Dict[str, Any]:
    if href.startswith(("https://", "http://")):
        url = href
    else:
        url = urllib.parse.urljoin(page_url, href)
    url, _, fragment = url.partition("#")
    if sha256 is None and fragment.startswith("sha256="):
        sha256 = fragment[len("sha256=") :]
    if isinstance(core_metadata, str):
        if core_metadata.startswith("sha256="):
            core_metadata = {"sha256": core_metadata[len("sha256=") :]}
        else:
            core_metadata = core_metadata.lower() == "true"
    return {
        "filename": "",
        "url": url,
        "sha256": sha256 or "",
        "requires_python": requires_python or "",
        "yanked": bool(yanked),
        "core_metadata": core_metadata or False,
    }


def ingest_index(page_url: str, body: str) -> Dict[str, Any]:
    """Compact an index page into its file entries."""
    text = body.lstrip()
    if text.startswith("{"):
        data = json.loads(text)
        files = []
        for item in data.get("files", []):
            entry = _file_entry(
                page_url,
                item.get("url", ""),
                requires_python=item.get("requires-python"),
                yanked=item.get("yanked", False),
                core_metadata=item.get(
                    "core-metadata", item.get("dist-info-metadata", False)
                ),
                sha256=(item.get("hashes") or {}).get("sha256"),
            )
            entry["filename"] = item.get("filename", "")
            files.append(entry)
        return {"files": files}

    parser = _IndexHTMLParser(page_url)
    parser.feed(body)
    return {"files": parser.files}


def ingest_metadata(body: str) -> Dict[str, Any]:
    """Keep the header of a core metadata file; the description is of no use."""
    normalized = body.replace("\r\n", "\n")
    header, _, _ = normalized.partition("\n\n")
    dynamic = []
    version = "1.0"
    for line in header.splitlines():
        lower = line.lower()
        if lower.startswith("dynamic:"):
            dynamic.append(line.partition(":")[2].strip().lower())
        elif lower.startswith("metadata-version:"):
            version = line.partition(":")[2].strip()
    return {"metadata": header, "dynamic": dynamic, "metadata_version": version}


class PageCache:
    """Candidates built from index pages, shared by the repositories of all targets.

    Building a `Candidate` parses the file name and its version, which does not
    depend on the target. A hub resolving several platforms would otherwise do
    it once per platform, and the solver asks for the same page many times.
    """

    def __init__(self) -> None:
        self._pages: Dict[str, List[Tuple[Dict[str, Any], Candidate]]] = {}

    def candidates(
        self, page: str, fact: Dict[str, Any]
    ) -> List[Tuple[Dict[str, Any], Candidate]]:
        cached = self._pages.get(page)
        if cached is None:
            cached = []
            for entry in fact.get("files", []):
                if entry.get("yanked"):
                    continue
                href = entry["url"] + (
                    "#sha256=" + entry["sha256"] if entry.get("sha256") else ""
                )
                candidate = filename_to_candidate((page, href), entry["filename"])
                if candidate is not None:
                    cached.append((entry, candidate))
            self._pages[page] = cached
        return cached


class FactRepository(Repository):
    """A package index as seen through the facts Bazel gathered.

    `prior` holds the distributions a previous solution chose for this target,
    keyed by normalized project name. They answer for their project's index page
    as long as the recorded version satisfies what is asked, which is how a
    re-resolution avoids fetching the pages of packages it does not change.
    """

    def __init__(
        self,
        index_url: str,
        facts: Dict[str, Any],
        requests: Requests,
        target: TargetEnvironment,
        allow_prerelease: bool,
        allow_sdists: bool,
        prior: Optional[Dict[NormName, Dict[str, Any]]] = None,
        pages: Optional[PageCache] = None,
    ) -> None:
        super().__init__("facts", allow_prerelease=allow_prerelease, target=target)
        self.index_url = index_url.rstrip("/")
        self.facts = facts
        self.requests = requests
        self.allow_sdists = allow_sdists
        self.prior = prior or {}
        self.pages = pages or PageCache()
        # `Requires-Python` expressions and wheel tags repeat across pages; each is
        # evaluated against the target once.
        self._python_ok: Dict[str, bool] = {}
        self._tags_ok: Dict[Tuple[Any, ...], bool] = {}
        self._candidates: Dict[str, List[Candidate]] = {}
        # The `--hash` values pinned per project; set by `solve` once the files are read.
        self.hashes: Dict[NormName, Set[str]] = {}
        self._entries: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def __repr__(self) -> str:
        return f"--index-url {self.index_url}"

    def __hash__(self) -> int:
        return hash(self.index_url)

    def page_url(self, name: str) -> str:
        return f"{self.index_url}/{normalize(name)}/"

    def known_pages(self) -> Iterable[str]:
        prefix = "index:" + self.index_url + "/"
        for key in self.facts:
            if key.startswith(prefix):
                yield key[len(prefix) :].rstrip("/")

    def request_page(self, name: str) -> None:
        page = self.page_url(name)
        self.requests.add(
            {
                "id": "index:" + page,
                "op": "fetch",
                "url": page,
                "headers": {"Accept": ACCEPT_INDEX},
                "ingest": "index",
            }
        )

    def _candidate(self, page: str, entry: Dict[str, Any]) -> Optional[Candidate]:
        href = entry["url"] + (
            "#sha256=" + entry["sha256"] if entry.get("sha256") else ""
        )
        candidate = filename_to_candidate((page, href), entry["filename"])
        if candidate is not None:
            self._entries[(page, entry["filename"])] = entry
        return candidate

    def candidates_for(
        self,
        name: str,
        req: Optional[packaging.requirements.Requirement] = None,
    ) -> List[Candidate]:
        """The candidates of a project whose page is known, those pinned by hash first."""
        page = self.page_url(name)
        candidates = self._candidates.get(page)
        if candidates is None:
            candidates = []
            # Artifacts that can never install on this target are left out, as the
            # solver would reject each of them on every request. One is kept when
            # all the installable ones are pre-releases and it is not, so that the
            # solver's pre-release policy sees what the full page would show it.
            spare: Optional[Candidate] = None
            fact = self.facts.get("index:" + page)
            if fact is not None and "files" in fact:
                for entry, candidate in self.pages.candidates(page, fact):
                    if not self._python_compatible(entry.get("requires_python") or ""):
                        continue
                    self._entries[(page, entry["filename"])] = entry
                    if self._installable(candidate):
                        candidates.append(candidate)
                    elif spare is None and not candidate.version.is_prerelease:
                        spare = candidate
            if spare is not None and all(c.version.is_prerelease for c in candidates):
                candidates.append(spare)
            self._candidates[page] = candidates
        return self._matching_hashes(name, candidates, req)

    def _installable(self, candidate: Candidate) -> bool:
        """Whether the wheel tags of a candidate fit the target, as `check_usability` decides."""
        key = (
            str(candidate.py_version) if candidate.py_version is not None else None,
            candidate.abi,
            tuple(candidate.platforms),
        )
        result = self._tags_ok.get(key)
        if result is None:
            result = (
                (
                    candidate.py_version is None
                    or candidate.py_version.check_compatibility(self.target)
                )
                and (
                    candidate.abi is None
                    or self.target.abi_tag_is_compatible(candidate.abi)
                )
                and any(
                    self.target.platform_tag_is_compatible(plat)
                    for plat in candidate.platforms
                )
            )
            self._tags_ok[key] = result
        return result

    def _python_compatible(self, requires_python: str) -> bool:
        if not requires_python:
            return True
        result = self._python_ok.get(requires_python)
        if result is None:
            try:
                result = check_python_compatibility(requires_python, self.target)
            except ValueError:
                LOG.warning(
                    "Ignoring an unparsable Requires-Python: %s", requires_python
                )
                result = True
            self._python_ok[requires_python] = result
        return result

    def _matching_hashes(
        self,
        name: str,
        candidates: List[Candidate],
        req: Optional[packaging.requirements.Requirement],
    ) -> List[Candidate]:
        """Keep the artifacts the requirement file pinned by hash, if it pinned any.

        When the pinned hashes match no artifact of the versions the requirement
        allows, the mismatch is reported for those versions: a pin bumped without
        its hash is the usual cause, and naming the new version's artifacts is
        what makes the message actionable.
        """
        pinned = self.hashes.get(utils.normalize_project_name(name))
        if not pinned or not candidates:
            return candidates
        matching = [
            candidate
            for candidate in candidates
            if self.entry(candidate)["sha256"] in pinned
        ]
        relevant = candidates
        if req is not None:
            relevant = [
                candidate
                for candidate in candidates
                if req.specifier.contains(candidate.version, prereleases=True)
            ] or candidates
        if any(candidate in matching for candidate in relevant):
            return matching
        raise HashMismatch(
            name,
            pinned,
            {
                candidate.filename or "": self.entry(candidate)["sha256"]
                for candidate in relevant
            },
        )

    def _recorded(
        self, req: packaging.requirements.Requirement
    ) -> Optional[List[Candidate]]:
        """The recorded distribution of a project, if it still satisfies `req`."""
        entry = self.prior.get(utils.normalize_project_name(req.name))
        if entry is None or not entry.get("filename") or not entry.get("url"):
            return None
        candidate = self._candidate(self.page_url(req.name), entry)
        if candidate is None:
            return None
        pinned = self.hashes.get(utils.normalize_project_name(req.name))
        if pinned and entry.get("sha256") not in pinned:
            return None
        # A recorded pre-release was accepted when it was recorded.
        if not filter_candidates(
            req, [candidate], allow_prereleases=True, target=self.target
        ):
            return None
        return [candidate]

    def candidates_or_request(
        self, req: packaging.requirements.Requirement
    ) -> Optional[List[Candidate]]:
        """The candidates of a requirement, or None after requesting its page."""
        if "index:" + self.page_url(req.name) in self.facts:
            return self.candidates_for(req.name, req)
        recorded = self._recorded(req)
        if recorded is not None:
            return recorded
        self.request_page(req.name)
        return None

    def get_candidates(
        self, req: Optional[packaging.requirements.Requirement]
    ) -> Sequence[Candidate]:
        if req is None:
            return []
        candidates = self.candidates_or_request(req)
        if candidates is None:
            raise NeedFacts()
        return candidates

    def entry(self, candidate: Candidate) -> Dict[str, Any]:
        """The index entry a candidate was made from."""
        page, _ = candidate.link
        return self._entries[(page, candidate.filename or "")]

    def metadata_key(self, candidate: Candidate) -> str:
        entry = self.entry(candidate)
        return "meta:" + (entry["sha256"] or entry["url"])

    def ensure_metadata(self, candidate: Candidate) -> Optional[Dict[str, Any]]:
        """The metadata fact of a candidate, requesting it when missing."""
        entry = self.entry(candidate)
        key = self.metadata_key(candidate)
        fact = self.facts.get(key)
        if fact is None:
            self.requests.add(
                {
                    "id": key,
                    "op": "metadata",
                    "url": entry["url"],
                    "sha256": entry["sha256"],
                    "core_metadata": entry.get("core_metadata", False),
                    "kind": (
                        "wheel" if candidate.type == DistributionType.WHEEL else "sdist"
                    ),
                    "filename": candidate.filename,
                }
            )
        return fact

    def resolve_candidate(
        self, candidate: Candidate
    ) -> Tuple[RequirementContainer, bool]:
        fact = self.ensure_metadata(candidate)
        if fact is None:
            raise NeedFacts()
        if "error" in fact:
            raise MetadataError(
                candidate.name, candidate.version, RuntimeError(fact["error"])
            )
        if candidate.type == DistributionType.SDIST:
            # Only PEP 643 static metadata can be trusted without running a build.
            version = packaging.version.Version(fact.get("metadata_version", "1.0"))
            if version < packaging.version.Version(
                "2.2"
            ) or "requires-dist" in fact.get("dynamic", []):
                raise MetadataError(
                    candidate.name,
                    candidate.version,
                    RuntimeError(
                        "the dependencies of this source distribution are not static metadata"
                    ),
                )
        dist = _parse_flat_metadata(_decode(fact["metadata"]))
        entry = self.entry(candidate)
        if entry["sha256"]:
            dist.hash = "sha256:" + entry["sha256"]
        dist.origin = self
        return dist, True


class _FactFiles:
    """Serve `open()` of requirement files from facts while a solve runs."""

    def __init__(self, facts: Dict[str, Any], requests: Requests) -> None:
        self.facts = facts
        self.requests = requests
        self._real_open = builtins.open

    def __enter__(self) -> "_FactFiles":
        builtins.open = self._open  # type: ignore[assignment]
        return self

    def __exit__(self, *exc: Any) -> None:
        builtins.open = self._real_open  # type: ignore[assignment]

    def _open(self, file: Any, *args: Any, **kwargs: Any) -> Any:
        mode = args[0] if args else kwargs.get("mode", "r")
        path = os.fspath(file) if not isinstance(file, int) else None
        if isinstance(path, str) and path.startswith(INPUT_ROOT + "/"):
            key = "file:" + path
            fact = self.facts.get(key)
            if fact is None:
                self.requests.add({"id": key, "op": "read", "path": path})
                raise NeedFacts()
            if "error" in fact:
                raise FileNotFoundError(fact["error"])
            text = _decode(fact["text"])
            if "b" in mode:
                return io.BytesIO(text.encode("utf-8"))
            return io.StringIO(text)
        return self._real_open(file, *args, **kwargs)


def _prior_locks(
    spec: Dict[str, Any], upgrade: Any
) -> Dict[str, Dict[NormName, Dict[str, Any]]]:
    """The recorded distributions per platform, minus the packages being upgraded.

    `prior` is either the recorded solution, `{"locks": {platform: {name: entry}}}`,
    or, for compatibility, a plain mapping of name to version, which pins but
    cannot stand in for index pages.
    """
    prior = spec.get("prior")
    if not prior or upgrade == "all":
        return {}
    skip = {utils.normalize_project_name(name) for name in (upgrade or [])}
    if "locks" in prior:
        locks = prior["locks"]
    else:
        locks = {
            platform: {name: {"version": version} for name, version in prior.items()}
            for platform in spec["platforms"]
        }
    result: Dict[str, Dict[NormName, Dict[str, Any]]] = {}
    for platform, packages in locks.items():
        entries: Dict[NormName, Dict[str, Any]] = {}
        for name, entry in packages.items():
            key = utils.normalize_project_name(entry.get("package") or name)
            if key in skip:
                continue
            entries[key] = entry
        result[platform] = entries
    return result


def _prior_pins(
    locks: Dict[str, Dict[NormName, Dict[str, Any]]],
) -> Dict[NormName, packaging.version.Version]:
    """The versions a prior solution chose, as soft pins."""
    pins: Dict[NormName, packaging.version.Version] = {}
    for packages in locks.values():
        for key, entry in packages.items():
            try:
                pins.setdefault(key, packaging.version.Version(entry["version"]))
            except (KeyError, packaging.version.InvalidVersion):
                continue
    return pins


class _Hub:
    def __init__(
        self,
        name: str,
        spec: Dict[str, Any],
        facts: Dict[str, Any],
        requests: Requests,
        upgrade: Any,
    ) -> None:
        self.name = name
        self.spec = spec
        self.targets = [
            TargetEnvironment.from_spec(platform, spec["python_version"])
            for platform in spec["platforms"]
        ]
        self.allow_sdists = bool(spec.get("allow_sdists", False))
        allow_prerelease = bool(spec.get("allow_prerelease", False))
        prior = _prior_locks(spec, upgrade)
        self.pins = _prior_pins(prior)
        self.indexes: List[List[FactRepository]] = []
        self.repos: List[Repository] = []
        pages = PageCache()
        for platform, target in zip(spec["platforms"], self.targets):
            inner = [
                FactRepository(
                    url,
                    facts,
                    requests,
                    target,
                    allow_prerelease,
                    self.allow_sdists,
                    prior=prior.get(platform),
                    pages=pages,
                )
                for url in spec["indexes"]
            ]
            self.indexes.append(inner)
            self.repos.append(
                inner[0] if len(inner) == 1 else MultiRepository(*inner, target=target)
            )


def _render(solution: DistributionCollection) -> Dict[str, Any]:
    packages: Dict[str, Any] = {}
    for node in solution:
        meta = node.metadata
        if meta is None or meta.meta or meta.candidate is None:
            continue
        page, href = meta.candidate.link
        url = urllib.parse.urljoin(page, href)
        url, _, fragment = url.partition("#")
        sha256 = fragment[len("sha256=") :] if fragment.startswith("sha256=") else ""
        via = []
        for reverse in node.reverse_deps:
            if reverse.metadata is not None and reverse.metadata.meta:
                via.append(reverse.metadata.name)
            else:
                via.append(reverse.key)
        core_metadata: Any = False
        hash_pinned = False
        if isinstance(meta.origin, FactRepository):
            core_metadata = meta.origin.entry(meta.candidate).get(
                "core_metadata", False
            )
            hash_pinned = node.key in meta.origin.hashes
        packages[node.key] = {
            "package": meta.name,
            "version": str(meta.version),
            "sha256": sha256,
            "url": url,
            "filename": meta.candidate.filename,
            "core_metadata": core_metadata,
            "hash_pinned": hash_pinned,
            "deps": sorted(dep.key for dep in node.dependencies),
            "via": sorted(via),
        }
    return packages


def _prefetch(hub: _Hub, req: packaging.requirements.Requirement) -> None:
    """Request the page of a requirement and the metadata of its best candidate per target."""
    for target, repos in zip(hub.targets, hub.indexes):
        if req.marker and not req.marker.evaluate(
            target.marker_environment_with_extra(None)
        ):
            continue
        for repo in repos:
            try:
                candidates = repo.candidates_or_request(req)
            except HashMismatch:
                continue
            if candidates is None:
                continue
            usable = filter_candidates(
                req,
                candidates,
                allow_prereleases=repo.allow_prerelease,
                target=target,
            )
            for candidate in sort_candidates(usable, target=target):
                if candidate.type == DistributionType.SDIST and not hub.allow_sdists:
                    continue
                repo.ensure_metadata(candidate)
                break


def _speculate(hubs: List[_Hub], facts: Dict[str, Any]) -> None:
    """Request what the next rounds will evidently need, to cut the number of rounds.

    The solver stops at the first missing fact, so without this every round would
    advance by one package. Instead, every requirement of the input files, every
    prior pin and every requirement named by known metadata gets its index page
    requested, together with the metadata of the candidate most likely chosen.
    Must run while `_FactFiles` is installed, as requirement files are read.
    """
    named: List[packaging.requirements.Requirement] = []
    for key, fact in facts.items():
        if not key.startswith("meta:") or "metadata" not in fact:
            continue
        for line in _decode(fact["metadata"]).splitlines():
            if not line.lower().startswith("requires-dist:"):
                continue
            try:
                req = utils.parse_requirement(line.partition(":")[2].strip())
            except ValueError:
                continue
            if req is None or (req.marker and "extra" in str(req.marker)):
                continue
            named.append(req)

    for hub in hubs:
        roots: List[packaging.requirements.Requirement] = []
        for path in hub.spec["requirements"] + list(hub.spec.get("constraints", [])):
            try:
                roots.extend(RequirementsFile.from_file(path))
            except NeedFacts:
                continue
        for name, version in hub.pins.items():
            roots.append(utils.parse_requirement("{}=={}".format(name, version)))
        for req in roots + named:
            _prefetch(hub, req)


def _ingest_documents(payload: Dict[str, Any], facts: Dict[str, Any]) -> Dict[str, Any]:
    """Turn the raw documents fetched since the last call into facts."""
    ingested = {}
    for key, document in sorted((payload.get("documents") or {}).items()):
        try:
            ingested[key] = ingest(document)
        except Exception as ex:  # pylint: disable=broad-except
            ingested[key] = {
                "error": "could not parse {}: {}".format(document.get("url", key), ex)
            }
    facts.update(ingested)
    return ingested


def solve(payload: Dict[str, Any]) -> Dict[str, Any]:
    facts = payload.get("facts") or {}
    ingested = _ingest_documents(payload, facts)
    requests = Requests()
    upgrade = payload.get("upgrade")
    hubs = [
        _Hub(name, spec, facts, requests, upgrade)
        for name, spec in sorted(payload["hubs"].items())
    ]

    results: Dict[str, Any] = {}
    with _FactFiles(facts, requests):
        try:
            for hub in hubs:
                input_reqs = [
                    RequirementsFile.from_file(path)
                    for path in hub.spec["requirements"]
                ]
                constraints = [
                    RequirementsFile.from_file(path)
                    for path in hub.spec.get("constraints", [])
                ]
                if hub.spec.get("enforce_hashes", True):
                    hashes = pinned_hashes(
                        hub.spec["requirements"] + list(hub.spec.get("constraints", []))
                    )
                    for repos in hub.indexes:
                        for repo in repos:
                            repo.hashes = hashes
                try:
                    solutions = perform_compile_group(
                        input_reqs,
                        hub.repos,
                        constraint_reqs=constraints or None,
                        remove_constraints=True,
                        only_binary=set() if hub.allow_sdists else AllOnlyBinarySet(),
                        pins=hub.pins,
                    )
                except (
                    NoCandidateException,
                    NoCommonVersionException,
                    MetadataError,
                    HashMismatch,
                ) as ex:
                    return {
                        "status": "error",
                        "hub": hub.name,
                        "message": str(ex),
                        "facts": ingested,
                    }
                results[hub.name] = {
                    "locks": {
                        platform: {"packages": _render(solution)}
                        for platform, (solution, _) in zip(
                            hub.spec["platforms"], solutions
                        )
                    }
                }
        except NeedFacts:
            _speculate(hubs, facts)
            return {"status": "need", "requests": requests.as_list(), "facts": ingested}

    consulted = sorted(key[len("meta:") :] for key in facts if key.startswith("meta:"))
    return {
        "status": "done",
        "hubs": results,
        "consulted": consulted,
        "facts": ingested,
    }


def ingest(payload: Dict[str, Any]) -> Dict[str, Any]:
    body = _decode(payload["body"])
    if payload["kind"] == "index":
        return ingest_index(payload["url"], body)
    if payload["kind"] == "metadata":
        return ingest_metadata(body)
    raise ValueError("unknown ingest kind {!r}".format(payload["kind"]))


def ping(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": "ok",
        "python": sys.version,
        "platform": sys.platform,
        "echo": payload.get("echo"),
    }


OPS = {"ingest": ingest, "solve": solve, "ping": ping}


def main(data: bytes) -> Tuple[bytes, int]:
    """Run one operation; returns the output and the return code of the call."""
    log = io.StringIO()
    handler = logging.StreamHandler(log)
    handler.setLevel(logging.WARNING)
    logging.getLogger().addHandler(handler)
    code = 0
    try:
        payload = json.loads(data.decode("utf-8"))
        result = OPS[payload["op"]](payload)
    except Exception:  # pylint: disable=broad-except
        result = {"status": "error", "message": traceback.format_exc()}
        code = 1
    finally:
        logging.getLogger().removeHandler(handler)
    if log.getvalue():
        result["log"] = log.getvalue()[-20000:]
    return json.dumps(result, sort_keys=True).encode("utf-8"), code
