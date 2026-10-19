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

import io
import json
import logging
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
from req_compile.wasm.files import (
    FactFiles,
    NeedFacts,
    Requests,
    RequirementsFileError,
    decode_text,
    file_constraints,
    pinned_hashes,
)

ACCEPT_INDEX = "application/vnd.pypi.simple.v1+json, text/html;q=0.1"

LOG = logging.getLogger("req_compile.wasm")


class HashMismatch(Exception):
    """No artifact of a project matches the hashes its requirement file pins."""

    def __init__(self, name: str, pinned: Set[str], found: Dict[str, str]) -> None:
        """`found` maps the sha256 of each artifact the indexes offer to its file name."""
        super().__init__(name)
        self.name = name
        self.pinned = pinned
        self.found = found

    def __str__(self) -> str:
        available = ", ".join(
            "{} ({})".format(filename, sha256[:12])
            for sha256, filename in sorted(
                self.found.items(), key=lambda item: (item[1], item[0])
            )
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


class UnpinnedPackage(Exception):
    """A requirement file pins hashes, but none for this project."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name

    def __str__(self) -> str:
        return (
            "`{}` is needed, but the requirement files pin no --hash for it. When a file "
            "pins hashes every package must be pinned, as with `pip --require-hashes`; "
            "otherwise an index could add a dependency the files never vouched for. Add "
            "it with its hash, or set `enforce_hashes = False`."
        ).format(self.name)


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
        indexes: Optional[Sequence[str]] = None,
        mismatches: Optional[Dict[NormName, "HashMismatch"]] = None,
    ) -> None:
        super().__init__("facts", allow_prerelease=allow_prerelease, target=target)
        self.index_url = index_url.rstrip("/")
        # Every index of the hub; a recorded distribution answers only for its own.
        self.indexes = {url.rstrip("/") for url in (indexes or [index_url])}
        # Hash mismatches per project, shared by the repositories of a hub: a
        # mismatch on one index is an error only if no index matches.
        self.mismatches: Dict[NormName, HashMismatch] = (
            mismatches if mismatches is not None else {}
        )
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

    def page_request(self, name: str) -> Dict[str, Any]:
        page = self.page_url(name)
        return {
            "id": "index:" + page,
            "op": "fetch",
            "url": page,
            "headers": {"Accept": ACCEPT_INDEX},
            "ingest": "index",
        }

    def request_page(self, name: str) -> None:
        self.requests.add(self.page_request(name))

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
        if not self.hashes or not candidates:
            return candidates
        key = utils.normalize_project_name(name)
        pinned = self.hashes.get(key)
        if not pinned:
            raise UnpinnedPackage(name)
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
        found = {
            self.entry(candidate)["sha256"]: candidate.filename or ""
            for candidate in relevant
        }
        mismatch = self.mismatches.get(key)
        if mismatch is None:
            self.mismatches[key] = HashMismatch(name, pinned, found)
        else:
            mismatch.found.update(found)
        return []

    def _recorded(
        self, req: packaging.requirements.Requirement
    ) -> Optional[List[Candidate]]:
        """The recorded distribution of a project, if it still satisfies `req`."""
        key = utils.normalize_project_name(req.name)
        entry = self.prior.get(key)
        if entry is None or not entry.get("filename") or not entry.get("url"):
            return None
        if self.hashes and key not in self.hashes:
            raise UnpinnedPackage(req.name)
        index = (entry.get("index") or "").rstrip("/")
        if index != self.index_url:
            # Recorded from another index. Its repository answers while that index
            # is still configured; once it is not, the page must be fetched.
            return [] if index in self.indexes else None
        if not self._python_compatible(entry.get("requires_python") or ""):
            return None
        candidate = self._candidate(self.page_url(req.name), entry)
        if candidate is None:
            return None
        pinned = self.hashes.get(key)
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

    def metadata_request(self, candidate: Candidate) -> Dict[str, Any]:
        entry = self.entry(candidate)
        return {
            "id": self.metadata_key(candidate),
            "op": "metadata",
            "url": entry["url"],
            "sha256": entry["sha256"],
            # Without a hash from the index the whole file is fetched, so that
            # the download's digest can pin it.
            "core_metadata": (
                entry.get("core_metadata", False) if entry["sha256"] else False
            ),
            "kind": "wheel" if candidate.type == DistributionType.WHEEL else "sdist",
            "filename": candidate.filename,
        }

    def ensure_metadata(self, candidate: Candidate) -> Optional[Dict[str, Any]]:
        """The metadata fact of a candidate, requesting it when missing."""
        fact = self.facts.get(self.metadata_key(candidate))
        if fact is None:
            self.requests.add(self.metadata_request(candidate))
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
        dist = _parse_flat_metadata(decode_text(fact["metadata"]))
        entry = self.entry(candidate)
        if entry["sha256"]:
            dist.hash = "sha256:" + entry["sha256"]
        dist.origin = self
        return dist, True


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
        self.mismatches: Dict[NormName, HashMismatch] = {}
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
                    indexes=spec["indexes"],
                    mismatches=self.mismatches,
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
        requires_python = ""
        index = ""
        if isinstance(meta.origin, FactRepository):
            entry = meta.origin.entry(meta.candidate)
            core_metadata = entry.get("core_metadata", False)
            requires_python = entry.get("requires_python") or ""
            index = meta.origin.index_url
            hash_pinned = node.key in meta.origin.hashes
            if not sha256:
                # The index gave no hash, so the file itself was fetched and the
                # download's digest pins it from here on.
                fact = meta.origin.facts.get(meta.origin.metadata_key(meta.candidate))
                sha256 = (fact or {}).get("sha256") or ""
        packages[node.key] = {
            "package": meta.name,
            "version": str(meta.version),
            "sha256": sha256,
            "url": url,
            "filename": meta.candidate.filename,
            "core_metadata": core_metadata,
            "hash_pinned": hash_pinned,
            "requires_python": requires_python,
            "index": index,
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
            except (HashMismatch, UnpinnedPackage):
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
    Must run while `FactFiles` is installed, as requirement files are read.
    """
    named: List[packaging.requirements.Requirement] = []
    for key, fact in facts.items():
        if not key.startswith("meta:") or "metadata" not in fact:
            continue
        for line in decode_text(fact["metadata"]).splitlines():
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


def _failed_requests(hub: "_Hub", ex: Exception) -> List[Dict[str, Any]]:
    """The requests behind a resolution error whose download failed.

    A failed index page or metadata download reaches the solver as an error fact,
    which it cannot tell from a project or distribution that does not exist. The
    host fetches these again, strictly, so that a network failure is reported as
    one and a page that really is missing is reported with its URL.
    """
    if isinstance(ex, NoCandidateException):
        name, version = ex.req.name, None
    elif isinstance(ex, NoCommonVersionException):
        name, version = ex.name, None
    elif isinstance(ex, MetadataError):
        name, version = ex.name, ex.version
    else:
        return []
    failed = Requests()
    for repos in hub.indexes:
        for repo in repos:
            page = repo.page_request(name)
            fact = repo.facts.get(page["id"])
            if fact is not None and "error" in fact:
                failed.add(page)
            try:
                candidates = repo.candidates_for(name)
            except (HashMismatch, UnpinnedPackage):
                continue
            # The solver reports a distribution whose metadata it could not get
            # as no candidate, so without a version every one is suspect.
            for candidate in candidates:
                if version is not None and candidate.version != version:
                    continue
                request = repo.metadata_request(candidate)
                fact = repo.facts.get(request["id"])
                if fact is not None and "error" in fact:
                    failed.add(request)
    return failed.as_list()


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
    with FactFiles(facts, requests) as files:
        try:
            for hub in hubs:
                files.current = hub.name
                try:
                    input_reqs = []
                    constraints = [
                        RequirementsFile.from_file(path)
                        for path in hub.spec.get("constraints", [])
                    ]
                    for path in hub.spec["requirements"]:
                        reqs = RequirementsFile.from_file(path)
                        input_reqs.append(reqs)
                        constraints.extend(
                            file_constraints(
                                path, reqs.parameters or [], hub.spec["indexes"]
                            )
                        )
                    if hub.spec.get("enforce_hashes", True):
                        hashes = pinned_hashes(
                            hub.spec["requirements"]
                            + list(hub.spec.get("constraints", []))
                        )
                        for repos in hub.indexes:
                            for repo in repos:
                                repo.hashes = hashes
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
                    UnpinnedPackage,
                    RequirementsFileError,
                ) as ex:
                    message = str(ex)
                    if isinstance(ex, NoCandidateException):
                        # No index had an artifact matching the pinned hashes.
                        mismatch = hub.mismatches.get(
                            utils.normalize_project_name(ex.req.name)
                        )
                        if mismatch is not None:
                            message = str(mismatch)
                    return {
                        "status": "error",
                        "hub": hub.name,
                        "message": message,
                        "retry": _failed_requests(hub, ex),
                        "facts": ingested,
                    }
                results[hub.name] = {
                    "locks": {
                        platform: {"packages": _render(solution)}
                        for platform, (solution, _) in zip(
                            hub.spec["platforms"], solutions
                        )
                    },
                    "files": sorted(files.reads.get(hub.name, ())),
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
    body = decode_text(payload["body"])
    if payload["kind"] == "index":
        return ingest_index(payload["url"], body)
    if payload["kind"] == "metadata":
        fact = ingest_metadata(body)
        if payload.get("sha256"):
            fact["sha256"] = payload["sha256"]
        return fact
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
