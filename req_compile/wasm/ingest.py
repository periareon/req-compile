"""Turn the documents Bazel downloads into facts: index pages and core metadata."""

import hashlib
import json
import urllib.parse
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple


def _is_sha256(value: Optional[str]) -> bool:
    return (
        bool(value)
        and len(value or "") == 64
        and all(c in "0123456789abcdefABCDEF" for c in value or "")
    )


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
    if sha256 is None:
        # A pip-style fragment may carry several hashes, `sha256=...&md5=...`.
        sha256 = urllib.parse.parse_qs(fragment).get("sha256", [None])[0]
    if isinstance(core_metadata, str):
        if core_metadata.startswith("sha256="):
            core_metadata = {"sha256": core_metadata[len("sha256=") :]}
        else:
            core_metadata = core_metadata.lower() == "true"
    if isinstance(core_metadata, dict) and not _is_sha256(core_metadata.get("sha256")):
        core_metadata = True
    return {
        "filename": "",
        "url": url,
        "sha256": sha256 if _is_sha256(sha256) else "",
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


# The header fields the solver reads; everything else in a METADATA file (the
# description, classifiers, project URLs) is dropped from the fact.
METADATA_FIELDS = (
    "metadata-version:",
    "name:",
    "version:",
    "requires-dist:",
    "requires-python:",
    "provides-extra:",
    "dynamic:",
)


def ingest_metadata(body: str) -> Dict[str, Any]:
    """The fields of a core metadata file the solver reads, and their digest.

    The digest keys the fact in the lockfile (`md:<digest>`), so distributions
    with identical metadata, such as one package's wheels for several platforms,
    are recorded once. Trimmed text can no longer be compared with the hash an
    index advertises for its metadata file; that comparison happens on download,
    and from then on the lock is the record.
    """
    normalized = body.replace("\r\n", "\n")
    header, _, _ = normalized.partition("\n\n")
    kept: List[str] = []
    keep = False
    for line in header.splitlines():
        if line[:1] in (" ", "\t"):
            # A folded continuation of the previous header line; unfolded, since
            # the solver reads one field per line.
            if keep:
                kept[-1] += " " + line.strip()
            continue
        keep = line.lower().startswith(METADATA_FIELDS)
        if keep:
            kept.append(line.rstrip())
    return metadata_fact("\n".join(kept))


def metadata_fact(text: str) -> Dict[str, Any]:
    """The fact of trimmed metadata text, as `ingest_metadata` produces it."""
    dynamic: List[str] = []
    version = "1.0"
    for line in text.splitlines():
        lower = line.lower()
        if lower.startswith("dynamic:"):
            # A multiple-use field, one name per line or several separated by commas.
            dynamic.extend(
                part.strip().lower()
                for part in line.partition(":")[2].split(",")
                if part.strip()
            )
        elif lower.startswith("metadata-version:"):
            version = line.partition(":")[2].strip()
    return {
        "metadata": text,
        "dynamic": dynamic,
        "metadata_version": version,
        "digest": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
