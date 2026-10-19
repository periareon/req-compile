"""Requirement files as the solver sees them: facts, includes, hashes and options.

Requirement files live under `INPUT_ROOT` inside the solver; Starlark maps those
paths back to labels. `FactFiles` serves `open()` of such paths from the facts
Bazel gathered, so the unmodified `req_compile` parsers read them as files.
"""

import builtins
import io
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Set

from req_compile import utils
from req_compile.containers import RequirementsFile
from req_compile.utils import NormName

# Requirement files are addressed by paths under this root; Starlark maps them to labels.
INPUT_ROOT = "/inputs"


class NeedFacts(Exception):
    """A fact the solver needs is missing; the round is over."""


class Requests:
    """The facts to obtain before the next round, deduplicated by id."""

    def __init__(self) -> None:
        self.by_id: Dict[str, Dict[str, Any]] = {}

    def add(self, request: Dict[str, Any]) -> None:
        self.by_id.setdefault(request["id"], request)

    def as_list(self) -> List[Dict[str, Any]]:
        return [self.by_id[key] for key in sorted(self.by_id)]


def decode_text(value: str) -> str:
    """Recover text that Starlark read as ISO-8859-1 and JSON encoded as is."""
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


class RequirementsFileError(Exception):
    """A requirement file asks for something the solver cannot honor."""


# `-r FILE` / `--requirement FILE`, split on whitespace like req-compile does.
_INCLUDE = re.compile(r"^(?:-r|--requirement)\s+(\S+)")


def pinned_hashes(paths: Iterable[str]) -> Dict[NormName, Set[str]]:
    """The `--hash` values the requirement files pin, by project.

    Follows `-r` includes like req-compile does. Files are read through `open()`,
    so this must run while `FactFiles` is installed.
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
            include = _INCLUDE.match(text)
            if include:
                visit(os.path.join(os.path.dirname(path), include.group(1)))
                continue
            if text.startswith("-"):
                continue
            comment = text.find(" #")
            if comment != -1:
                text = text[:comment]
            parts = text.split()
            # `--hash=ALG:DIGEST` and `--hash ALG:DIGEST` are both pip syntax.
            hashes: Set[str] = set()
            spec_parts: List[str] = []
            index = 0
            while index < len(parts):
                part = parts[index]
                index += 1
                if part == "--hash" and index < len(parts):
                    value = parts[index]
                    index += 1
                elif part.startswith("--hash="):
                    value = part[len("--hash=") :]
                else:
                    if not part.startswith("--"):
                        spec_parts.append(part)
                    continue
                algorithm, _, digest = value.partition(":")
                if algorithm != "sha256" or not digest:
                    raise RequirementsFileError(
                        "{}: only `--hash=sha256:...` is supported, not `{}`".format(
                            path, value
                        )
                    )
                hashes.add(digest)
            if not hashes:
                continue
            try:
                req = utils.parse_requirement(" ".join(spec_parts))
            except ValueError:
                continue
            if req is not None:
                result.setdefault(utils.normalize_project_name(req.name), set()).update(
                    hashes
                )

    for path in paths:
        visit(path)
    return result


class FactFiles:
    """Serve `open()` of requirement files from facts while a solve runs."""

    def __init__(self, facts: Dict[str, Any], requests: Requests) -> None:
        self.facts = facts
        self.requests = requests
        self._real_open = builtins.open
        # The input files read, per hub; the host records them with the solution
        # so that a change to an included file is seen.
        self.current: Optional[str] = None
        self.reads: Dict[str, Set[str]] = {}

    def __enter__(self) -> "FactFiles":
        builtins.open = self._open  # type: ignore[assignment]
        return self

    def __exit__(self, *exc: Any) -> None:
        builtins.open = self._real_open  # type: ignore[assignment]

    def _open(self, file: Any, *args: Any, **kwargs: Any) -> Any:
        mode = args[0] if args else kwargs.get("mode", "r")
        path = os.fspath(file) if not isinstance(file, int) else None
        if isinstance(path, str) and os.sep != "/":
            # Included files are joined with `os.path.join`, which on a Windows
            # host (the native tests) puts a backslash under the posix root.
            path = path.replace(os.sep, "/")
        if isinstance(path, str) and path.startswith(INPUT_ROOT + "/"):
            if self.current is not None:
                self.reads.setdefault(self.current, set()).add(path)
            key = "file:" + path
            fact = self.facts.get(key)
            if fact is None:
                self.requests.add({"id": key, "op": "read", "path": path})
                raise NeedFacts()
            if "error" in fact:
                raise FileNotFoundError(fact["error"])
            text = decode_text(fact["text"])
            if "b" in mode:
                return io.BytesIO(text.encode("utf-8"))
            return io.StringIO(text)
        return self._real_open(file, *args, **kwargs)


_INDEX_OPTIONS = ("-i", "--index-url", "--extra-index-url")


def file_constraints(
    path: str, parameters: List[str], indexes: Iterable[str]
) -> List[RequirementsFile]:
    """The `-c` constraint files a requirements file names, checking its other options.

    An index option is accepted when it names an index the hub is configured with,
    which is what req-compile's own lock files and pip-compile's output carry, and
    refused otherwise. Every other option is refused rather than dropped: a
    find-links or binary option that silently did not apply would resolve
    differently from what the file says. The equivalent attribute of the `parse`
    tag is where they go.
    """
    configured = {url.rstrip("/") for url in indexes}
    result: List[RequirementsFile] = []
    problems: List[str] = []
    index = 0
    while index < len(parameters):
        token = parameters[index]
        index += 1
        option, equals, value = token.partition("=")
        if not equals and option in ("-c", "--constraint", *_INDEX_OPTIONS):
            if index < len(parameters):
                value = parameters[index]
                index += 1
        if option in ("-c", "--constraint"):
            result.append(
                RequirementsFile.from_file(os.path.join(os.path.dirname(path), value))
            )
        elif option in _INDEX_OPTIONS:
            if value.rstrip("/") not in configured:
                problems.append(
                    "{} {} names an index the hub is not configured with".format(
                        option, value
                    )
                )
        elif option.startswith("-"):
            problems.append("{} is not applied by the Bazel solver".format(option))
    if problems:
        raise RequirementsFileError(
            "{}: {}; set the equivalent attribute on the `parse` tag instead.".format(
                path, "; ".join(sorted(set(problems)))
            )
        )
    return result
