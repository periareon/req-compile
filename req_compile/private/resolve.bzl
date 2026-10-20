"""Resolve requirements inside the module extension with the WebAssembly solver.

The solver is the unmodified `req_compile` package running on CPython inside a
WebAssembly module (see `wasm/README.md`). Bazel runs it with `execute_wasm`,
which cannot perform any I/O, so resolution happens in rounds: the solver is
called with every fact gathered so far, answers either with a solution or with
the files and downloads it is missing, this code performs them, and calls again.
Requirement files are read with `ctx.read`, which records them as inputs of the
extension, so the lock entry Bazel writes is invalidated when they change.

Across evaluations the extension remembers, through Bazel's lockfile `facts`, the
solution of each hub together with the inputs it was solved from, and the metadata
of every distribution it chose. A hub whose inputs did not change is rebuilt
from its recorded solution without loading the solver. A hub whose inputs changed
is re-solved with the recorded versions as soft pins and the recorded metadata on
hand, so only what the change touches is fetched. `REQ_COMPILE_UPGRADE=<package>[,<package>]`
(or `all`) drops the pins; `requirements.update -- --upgrade <package>` sets it for a nested run.

Nothing here runs unless a hub asks for it, and then only when Bazel's
WebAssembly support is enabled; see `require_wasm`.
"""

load("@bazel_tools//tools/build_defs/repo:utils.bzl", "read_user_netrc", "use_netrc")
load(":solver.bzl", "SOLVER_SHA256", "SOLVER_URL")
load(":utils.bzl", "sanitize_package_name")

# Requirement files are addressed by paths under this root inside the solver.
INPUT_ROOT = "/inputs"

# The layout of the `solution:<hub>` facts. Facts survive changes to this code, so
# a fact of another schema is ignored rather than misread.
FACTS_SCHEMA = 1

UPGRADE_ENV = "REQ_COMPILE_UPGRADE"

_WASM_FLAGS = (
    "Resolving requirements inside Bazel needs `execute_wasm`, which is experimental. Add " +
    "`common --experimental_repository_ctx_execute_wasm` to your `.bazelrc` (Bazel 9.3 or newer), and " +
    "`common --experimental_repository_ctx_wasm_compilation` with Bazel 10 or newer, which is several " +
    "times faster. Alternatively compile lock files with `py_reqs_compiler` and use `requirements_locks`."
)

def wasm_available(ctx):
    """Whether Bazel exposes `execute_wasm` on this context."""
    return hasattr(ctx, "load_wasm") and hasattr(ctx, "execute_wasm")

def require_wasm(ctx, hub_names):
    """Fail with instructions when the hubs need the solver but Bazel cannot run it."""
    if not wasm_available(ctx):
        fail("Hub(s) {} use `requirements_in`. {}".format(", ".join(sorted(hub_names)), _WASM_FLAGS))

def resolve_spec(
        name,
        requirements_in,
        python_version,
        platforms,
        solver = None,
        constraints = [],
        pins = None,
        index_urls = ["https://pypi.org/simple"],
        allow_sdists = False,
        allow_prerelease = False,
        enforce_hashes = True,
        max_rounds = 40,
        memory_limit = 1024 * 1024 * 1024,
        timeout = 3600):
    """Describe a hub to resolve from requirement files.

    Args:
        name (str): The name of the hub.
        requirements_in (list[Label]): The requirement files.
        python_version (str): The Python version to resolve for, e.g. `3.11` or `3.11.4`.
        platforms (list[str]): Wheel platform tags to resolve for, one lock per tag.
        solver (Label): The WebAssembly solver module; None for the one of this release.
        constraints (list[Label]): Constraint files, never themselves installed.
        pins (Label): The hub's pinned requirements file, which pins the version and
            hashes of the packages it lists and which the hub keeps in step with its
            solution (`requirements.update`); None when the hub has none.
        index_urls (list[str]): Package indexes, searched in order.
        allow_sdists (bool): Whether source distributions with static metadata may be used.
        allow_prerelease (bool): Whether pre-releases may be selected.
        enforce_hashes (bool): Whether `--hash` values in the files must match the artifacts.
        max_rounds (int): The most rounds of requests before giving up.
        memory_limit (int): The memory limit of a solver call, in bytes.
        timeout (int): The timeout of a solver call, in seconds.

    Returns:
        struct: The resolve specification.
    """
    return struct(
        name = name,
        requirements_in = list(requirements_in),
        constraints = list(constraints),
        pins = pins,
        python_version = python_version,
        platforms = list(platforms),
        solver = solver,
        index_urls = list(index_urls),
        allow_sdists = allow_sdists,
        allow_prerelease = allow_prerelease,
        enforce_hashes = enforce_hashes,
        max_rounds = max_rounds,
        memory_limit = memory_limit,
        timeout = timeout,
    )

def _input_path(label):
    """The path a requirement file has inside the solver."""
    parts = [INPUT_ROOT, label.repo_name or "_main"]
    if label.package:
        parts.append(label.package)
    parts.append(label.name)
    return "/".join(parts)

def _normalize(path):
    """Resolve `.` and `..` segments, which `-r` includes produce."""
    parts = []
    for segment in path.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if parts:
                parts.pop()
            continue
        parts.append(segment)
    return "/" + "/".join(parts)

def _label_for_path(path, known):
    """Map a path inside the solver back to the label of the file."""
    normalized = _normalize(path)
    if normalized in known:
        return known[normalized]
    if not normalized.startswith(INPUT_ROOT + "/"):
        fail("The solver asked for a file outside of its inputs: {}".format(path))

    # A file included by a known one stays in that file's package whatever
    # subdirectories the include goes through: a subdirectory without a BUILD
    # file is no package of its own. The longest matching directory wins.
    best = None
    for known_path, label in known.items():
        directory = known_path.rsplit("/", 1)[0] + "/"
        if normalized.startswith(directory) and (best == None or len(directory) > len(best[0])):
            best = (directory, label)
    if best != None:
        directory, label = best
        prefix = label.name.rsplit("/", 1)[0] + "/" if "/" in label.name else ""
        return Label("@@{}//{}:{}".format(label.repo_name, label.package, prefix + normalized[len(directory):]))

    # Otherwise the path is read as `/inputs/<repo>/<package>/<name>`.
    parts = normalized[len(INPUT_ROOT) + 1:].split("/")
    if len(parts) < 2:
        fail("The solver asked for a file it cannot name: {}".format(path))
    repo = "" if parts[0] == "_main" else parts[0]
    return Label("@@{}//{}:{}".format(repo, "/".join(parts[1:-1]), parts[-1]))

def _solver_module(ctx, spec):
    """The path of the solver module: the one a tag names, else this release's, downloaded.

    The download goes through Bazel's repository cache, so the module is fetched
    once per machine per release.
    """
    if spec.solver != None:
        return ctx.path(spec.solver)
    if not SOLVER_SHA256:
        fail(
            "This checkout of rules_req_compile is not a release, so it carries no solver module. " +
            "Build one with `wasm/build_solver.sh` and name it with `solver` on the `resolve` tag, " +
            "or depend on a released version.",
        )
    ctx.download(url = SOLVER_URL, output = "req_compile_solver.wasm", sha256 = SOLVER_SHA256)
    return ctx.path("req_compile_solver.wasm")

def _solver_id(spec):
    """What identifies the solver a hub uses, for grouping and for the recorded inputs."""
    if spec.solver != None:
        return str(spec.solver)
    return "release:" + SOLVER_SHA256

def _run(ctx, module, limits, payload):
    result = ctx.execute_wasm(
        module,
        "solve",
        input = json.encode(payload),
        timeout = limits.timeout,
        memory_limit = limits.memory_limit,
    )
    if result.return_code != 0:
        fail("The requirements solver failed (code {}): {}\n{}".format(
            result.return_code,
            result.error_message,
            result.output[:8000],
        ))
    return json.decode(result.output)

def _metadata_text(ctx, request, path):
    """The core metadata of a downloaded distribution."""
    if request["core_metadata"]:
        return ctx.read(path)

    # The whole distribution was downloaded: a wheel carries `.dist-info/METADATA`,
    # a source distribution its PEP 643 `PKG-INFO` in its top directory. Entries
    # are visited in name order, and the directory named after the distribution
    # first, so that the choice does not depend on how the archive was laid out.
    output = path + ".d"
    ctx.extract(path, output = output)
    filename = request.get("filename") or ""
    stem = "-".join(filename.split("-")[:2])
    entries = sorted(ctx.path(output).readdir(), key = lambda entry: (entry.basename != stem and entry.basename != stem + ".dist-info", entry.basename))
    if request.get("kind") == "sdist":
        for entry in entries:
            if entry.is_dir and entry.get_child("PKG-INFO").exists:
                return ctx.read(entry.get_child("PKG-INFO"))
        fail("No `PKG-INFO` in {}".format(request["url"]))
    for entry in entries:
        if entry.basename.endswith(".dist-info"):
            return ctx.read(entry.get_child("METADATA"))
    fail("No `.dist-info/METADATA` in {}".format(request["url"]))

# What a package of a solution records beyond the `parse_lockfile` shape. The
# solver uses them to stand in for the index page of a package a re-resolution
# keeps: `filename` and `url` make the candidate, `index` and `requires_python`
# decide whether it may answer, `core_metadata` whether the index serves its
# metadata separately, `metadata` names the `md:` fact holding its metadata, and
# `sidecar` whether that metadata came from the index's separate file rather
# than the distribution (the solver reads the latter for a hash-pinned artifact).
#
# In the lockfile an artifact is keyed by its sha256 (or its URL when the index
# gave none), so neither is repeated inside it; `index` is left out when it is
# the index the solution records as its first (the hub's first index at the time,
# kept with the solution so that a later change of index cannot misattribute a
# recorded artifact), and `core_metadata` is reduced to whether a separate
# metadata file exists, since the `md:` fact makes fetching it again unnecessary.
_ARTIFACT_DEFAULTS = {
    "core_metadata": False,
    "metadata": "",
    "requires_python": "",
    "sidecar": False,
}

def _is_sha256(value):
    return len(value) == 64 and value.lower().strip("0123456789abcdef") == ""

def _package_entry(data, deps):
    """A package in the shape `parse_lockfile` produces, with the solver's extras."""
    url = data.get("url", "")
    return {
        "annotations": {},
        "constraint": None,
        "core_metadata": data.get("core_metadata", False),
        "deps": sorted(deps),
        # The file name is the last segment of the URL's path; a query string
        # (a signed URL) is not part of it.
        "filename": data.get("filename") or url.partition("?")[0].rpartition("/")[2],
        "index": data.get("index", ""),
        "metadata": data.get("metadata", ""),
        "package": data["package"],
        "requires_python": data.get("requires_python", ""),
        "sha256": data.get("sha256", ""),
        "sidecar": data.get("sidecar", False),
        "url": url,
        "version": data["version"],
        "via": None,
        "whl": None,
    }

def _lock_packages(packages):
    """Convert the solver's packages into the structure `parse_lockfile` produces."""
    return {
        sanitize_package_name(data["package"]): _package_entry(
            data,
            [sanitize_package_name(dep) for dep in data["deps"]],
        )
        for data in packages.values()
    }

def _compact_locks(locks, spec):
    """Locks as the lockfile stores them: each artifact once, and per platform the pick.

    Most packages resolve to the same file on every platform, with the same
    dependencies; storing the file once, its dependencies with it, and per
    platform only `package -> artifact` is what keeps the solution fact small. A
    platform whose dependencies differ (environment markers) records its own with
    the pick. Fields at their default are left out.
    """
    artifacts = {}
    picks = {}
    for platform, packages in locks.items():
        picks[platform] = {}
        for name, data in packages.items():
            aid = data["sha256"] or data["url"]
            artifact = artifacts.get(aid)
            if artifact == None:
                artifact = {"deps": data["deps"], "package": data["package"], "version": data["version"]}
                if data["sha256"] and data["url"]:
                    artifact["url"] = data["url"]
                if data["index"] and data["index"] != spec.index_urls[0]:
                    artifact["index"] = data["index"]
                for key, default in _ARTIFACT_DEFAULTS.items():
                    if data.get(key, default) != default:
                        artifact[key] = data[key]
                if artifact.get("core_metadata"):
                    artifact["core_metadata"] = True
                artifacts[aid] = artifact
            if data["deps"] == artifact["deps"]:
                picks[platform][name] = aid
            else:
                picks[platform][name] = {"artifact": aid, "deps": data["deps"]}
    return {"artifacts": artifacts, "index": spec.index_urls[0], "locks": picks}

def _expand_locks(recorded):
    """The per-platform packages of a recorded solution, as `_lock_packages` makes them."""
    artifacts = {}
    for aid, stored in recorded["artifacts"].items():
        artifact = dict(_ARTIFACT_DEFAULTS, index = recorded["index"], **stored)
        if _is_sha256(aid):
            artifact["sha256"] = aid
            artifact.setdefault("url", "")
        else:
            artifact["sha256"] = ""
            artifact["url"] = aid
        artifacts[aid] = artifact
    locks = {}
    for platform, packages in recorded["locks"].items():
        locks[platform] = {}
        for name, pick in packages.items():
            if type(pick) == "string":
                artifact = artifacts[pick]
                deps = artifact["deps"]
            else:
                artifact = artifacts[pick["artifact"]]
                deps = pick["deps"]
            locks[platform][name] = _package_entry(artifact, deps)
    return locks

def _fact(ctx, key):
    """A fact recorded by a previous evaluation, or None."""
    facts = getattr(ctx, "facts", None)
    if facts == None:
        return None
    return facts.get(key)

def _upgrade(ctx):
    """What `REQ_COMPILE_UPGRADE` asks for: None, "all" or a list of packages."""
    value = ctx.getenv(UPGRADE_ENV)
    if not value:
        return None
    if value.strip().lower() == "all":
        return "all"
    return [name.strip() for name in value.split(",") if name.strip()]

def _hub_inputs(ctx, spec):
    """Everything a hub's solution depends on, read so that Bazel records it."""
    return {
        "attrs": {
            "allow_prerelease": spec.allow_prerelease,
            "allow_sdists": spec.allow_sdists,
            "constraints": [_input_path(label) for label in spec.constraints],
            "enforce_hashes": spec.enforce_hashes,
            "index_urls": spec.index_urls,
            "pins": _input_path(spec.pins) if spec.pins != None else "",
            "platforms": spec.platforms,
            "python_version": spec.python_version,
            "requirements_in": [_input_path(label) for label in spec.requirements_in],
            "solver": _solver_id(spec),
        },
        "files": {
            _input_path(label): ctx.read(label)
            for label in _input_labels(spec)
        },
    }

def _input_labels(spec):
    """The files a hub names: requirements, constraints and the pinned file."""
    return spec.requirements_in + spec.constraints + ([spec.pins] if spec.pins != None else [])

def _meaningful(text):
    """A requirement file reduced to the lines that can change its solution.

    Comments, blank lines and trailing whitespace are dropped, so that the
    recorded inputs are small and an edit to a comment does not re-solve.
    """
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            lines.append(line.rstrip())
    return "\n".join(lines)

def _recorded_inputs(inputs):
    """The inputs as the solution fact records them: files by their meaningful lines."""
    return {
        "attrs": inputs["attrs"],
        "files": {path: _meaningful(text) for path, text in inputs["files"].items()},
    }

def _unchanged(ctx, spec, previous, current):
    """Whether a recorded solution's inputs are the current ones, included files too.

    `current` holds the files the tag names; the files those include are known
    only from the recorded solution, so they are read here, which also makes Bazel
    watch them. They are added to `current`.
    """
    recorded = previous["inputs"]
    if recorded.get("attrs") != current["attrs"]:
        return False
    files = recorded.get("files", {})
    for path, text in current["files"].items():
        if files.get(path) != _meaningful(text):
            return False
    known = {_input_path(label): label for label in _input_labels(spec)}
    for path, text in files.items():
        if path in current["files"]:
            continue
        label = _label_for_path(path, known)
        if not ctx.path(label).exists:
            return False
        actual = ctx.read(label)
        if _meaningful(actual) != text:
            return False
        current["files"][path] = actual
    return True

def _thaw(value):
    """A mutable deep copy of a value read from the lockfile's facts, which are frozen."""
    return json.decode(json.encode(value))

def _recorded_solution(ctx, spec):
    """The solution a previous evaluation recorded for a hub, if it is usable.

    Returns `inputs`, the per-platform `locks` expanded to the working shape, and
    `raw`, the fact as stored, to store again when the hub is unchanged.
    """
    recorded = _fact(ctx, "solution:" + spec.name)
    if type(recorded) != "dict" or recorded.get("schema") != FACTS_SCHEMA:
        return None
    if sorted(recorded.get("locks", {}).keys()) != sorted(spec.platforms):
        return None
    recorded = _thaw(recorded)
    return {
        "inputs": recorded["inputs"],
        "locks": _expand_locks(recorded),
        "raw": recorded,
    }

def _referenced_metadata(locks, texts):
    """The `md:` facts the packages of `locks` refer to, out of `texts` (digest to text)."""
    facts = {}
    for packages in locks.values():
        for data in packages.values():
            digest = data.get("metadata")
            if digest and digest in texts:
                facts["md:" + digest] = texts[digest]
    return facts

def _recorded_metadata(ctx, locks):
    """The `md:` facts of a recorded solution's packages, from the lockfile.

    `module_ctx.facts` can only be looked up by key, so the digests come from the
    recorded solution rather than from enumerating the facts.
    """
    facts = {}
    for packages in locks.values():
        for data in packages.values():
            digest = data.get("metadata")
            if digest and "md:" + digest not in facts:
                text = _fact(ctx, "md:" + digest)
                if type(text) == "string":
                    facts["md:" + digest] = text
    return facts

def _start_download(ctx, netrc, request, scratch, allow_fail, block = False):
    """Start the download a `fetch` or `metadata` request asks for.

    Args:
        ctx (module_ctx): The extension context.
        netrc (dict): The user's netrc, for authentication.
        request (dict): The solver's request.
        scratch (int): A number unique to this download, naming its file.
        allow_fail (bool): Whether a failed download is reported through the
            token rather than raised.
        block (bool): Whether to wait for the download here.

    Returns:
        tuple: The request, the path the download lands at and the download token
            (or result, when blocking).
    """
    if request["op"] == "fetch":
        path = "req_compile_resolve/{}.page".format(scratch)
        url = request["url"]
        sha256 = ""
        headers = request.get("headers", {})
    elif request["op"] == "metadata":
        core = request["core_metadata"]
        headers = {}
        if core:
            path = "req_compile_resolve/{}.metadata".format(scratch)

            # PEP 658: the metadata file sits next to the distribution; a query
            # string (a signed URL) stays after the suffix.
            base, query_mark, query = request["url"].partition("?")
            url = base + ".metadata" + query_mark + query
            sha256 = core["sha256"] if type(core) == "dict" else ""
        else:
            # The whole distribution; its extension tells `extract` the format.
            path = "req_compile_resolve/{}/{}".format(scratch, request.get("filename") or "dist.whl")
            url = request["url"]
            sha256 = request["sha256"]
    else:
        fail("The requirements solver made an unknown request: {}".format(json.encode(request)))
    return request, path, ctx.download(
        url = url,
        output = path,
        sha256 = sha256,
        headers = headers,
        auth = use_netrc(netrc, [url], {}),
        allow_fail = allow_fail,
        block = block,
    )

def _document(ctx, request, path, result):
    """The document to hand the solver for a download that succeeded."""
    if request["op"] == "fetch":
        return {"body": ctx.read(path), "kind": "index", "url": request["url"]}
    document = {
        "body": _metadata_text(ctx, request, path),
        "kind": "metadata",
        # Whether this is the index's separately served metadata file.
        "sidecar": bool(request["core_metadata"]),
        "url": request["url"],
    }
    if not request["core_metadata"]:
        # The whole file was fetched; its digest pins it when the index gave none.
        document["sha256"] = result.sha256
    return document

def _resolve_group(ctx, specs, inputs, recorded, upgrade):
    """Resolve the hubs sharing a solver module, in one loop.

    Args:
        ctx (module_ctx): The extension context.
        specs (list[struct]): The `resolve_spec`s of the hubs.
        inputs (dict): Hub name to `_hub_inputs`.
        recorded (dict): Hub name to the solution a previous evaluation recorded, if any.
        upgrade: What to re-resolve from the indexes: `None`, `"all"` or a list of package names
            (see `_upgrade`).

    Returns:
        tuple: The resolved hubs and the metadata texts their packages refer to, by digest.
    """
    first = specs[0]
    module = ctx.load_wasm(_solver_module(ctx, first))
    netrc = read_user_netrc(ctx)

    # The hubs share the calls, so the most generous limits among them apply.
    limits = struct(
        max_rounds = max([spec.max_rounds for spec in specs]),
        memory_limit = max([spec.memory_limit for spec in specs]),
        timeout = max([spec.timeout for spec in specs]),
    )

    known = {}
    hubs = {}
    facts = {}
    for spec in specs:
        for label in _input_labels(spec):
            known[_input_path(label)] = label
        hubs[spec.name] = {
            "allow_prerelease": spec.allow_prerelease,
            "allow_sdists": spec.allow_sdists,
            "constraints": [_input_path(label) for label in spec.constraints],
            "enforce_hashes": spec.enforce_hashes,
            "indexes": spec.index_urls,
            "pins": _input_path(spec.pins) if spec.pins != None else None,
            "platforms": spec.platforms,
            "python_version": spec.python_version,
            "requirements": [_input_path(label) for label in spec.requirements_in],
        }

        # The requirement files were already read; the first round need not ask.
        for path, text in inputs[spec.name]["files"].items():
            facts["file:" + path] = {"text": text}

        # The recorded solution pins versions and stands in for index pages, and
        # the metadata recorded with it saves every download for those versions.
        previous = recorded.get(spec.name)
        if previous and upgrade != "all":
            hubs[spec.name]["prior"] = {"locks": previous["locks"]}

            # The metadata of every recorded distribution, which the solver joins
            # to the distributions of the prior solution.
            facts.update(_recorded_metadata(ctx, previous["locks"]))

    documents = {}
    solution = None
    scratch = 0
    for round_number in range(1, limits.max_rounds + 1):
        ctx.report_progress("Resolving {}: round {} ({} facts)".format(
            ", ".join(sorted(hubs)),
            round_number,
            len(facts),
        ))
        out = _run(ctx, module, limits, {
            "documents": documents,
            "facts": facts,
            "hubs": hubs,
            "op": "solve",
            "upgrade": upgrade,
        })
        facts.update(out.get("facts", {}))
        documents = {}
        if out["status"] == "done":
            solution = out
            break
        if out["status"] == "error":
            # A download that failed reached the solver as a missing project or
            # distribution, and the solver names the requests behind its error
            # whose download failed. Fetch those again, one at a time, and when
            # one still fails report that instead of the solver's explanation:
            # the URL, Bazel's cause (a connection refused, a 404) and how to
            # recover. The recovery note matters because every error of a module
            # extension is persistent to Skyframe (Bazel wraps the evaluation's
            # `EvalException` in `SingleExtensionEvalFunctionException` with
            # `Transience.PERSISTENT`, a download error included, where a
            # repository rule's fetch keeps it transient), so the same command
            # replays the failure until an input of the extension changes or
            # the server restarts. In the default lockfile mode Bazel rewrites
            # `MODULE.bazel.lock` after the failed command and the extension
            # depends on it, so the next command does evaluate again; with
            # `--lockfile_mode=off` the error comes back until `bazel shutdown`
            # (both measured, Bazel 10.0.0rc1). When every fetch succeeds the
            # solve goes on with the documents.
            retry = out.get("retry", [])
            if not retry:
                hub = out.get("hub", "?")
                hint = ""
                if hubs.get(hub, {}).get("pins"):
                    # A pin the requirements no longer allow is dropped by itself;
                    # what can still stand in the way is a hash the file gives for
                    # a version. The `--upgrade` flag of `requirements.update`
                    # cannot help here: `bazel run` resolves the hub before the
                    # script runs.
                    hint = (
                        "\nIf the hashes {} gives for a version are the cause, resolve the package without " +
                        "them: `REQ_COMPILE_UPGRADE=<package>[,<package>] bazel run @{}//:requirements.update` " +
                        "(`all` for every package)."
                    ).format(hubs[hub]["pins"], hub)
                fail("Failed to resolve the requirements of hub `{}`: {}{}".format(hub, out["message"], hint))
            for request in retry:
                scratch += 1
                request, path, result = _start_download(ctx, netrc, request, scratch, allow_fail = True, block = True)
                if not result.success:
                    # Bazel 10 reports the cause in `error`; Bazel 9 only says it failed.
                    fail((
                        "Failed to resolve the requirements of hub `{}`: could not download {}: {}\n" +
                        "Once the cause is fixed, run the command again; if this error comes back although " +
                        "the index is reachable, Bazel is replaying the failed evaluation: `bazel shutdown` clears it."
                    ).format(out.get("hub", "?"), request["url"], getattr(result, "error", "download failed")))
                facts.pop(request["id"], None)
                documents[request["id"]] = _document(ctx, request, path, result)
            continue

        pending = []
        for request in out["requests"]:
            if request["op"] == "read":
                facts[request["id"]] = {"text": ctx.read(_label_for_path(request["path"], known))}
                continue

            scratch += 1
            pending.append(_start_download(ctx, netrc, request, scratch, allow_fail = True))

        for request, path, token in pending:
            result = token.wait()
            if result.success:
                documents[request["id"]] = _document(ctx, request, path, result)
            else:
                facts[request["id"]] = {"error": "download failed: {}".format(request["url"])}

    if solution == None:
        fail("Resolving {} did not converge in {} rounds. Raise `max_rounds` if the dependency graph is unusually deep.".format(
            ", ".join(sorted(hubs)),
            limits.max_rounds,
        ))

    resolved = {}
    for spec in specs:
        locks = solution["hubs"][spec.name]["locks"]
        resolved[spec.name] = {
            platform: _lock_packages(locks[platform]["packages"])
            for platform in spec.platforms
        }

        # The files the hub's requirement files included, so that a change to
        # one of them is seen by the next evaluation.
        for path in solution["hubs"][spec.name].get("files", []):
            normalized = _normalize(path)
            if normalized not in inputs[spec.name]["files"]:
                inputs[spec.name]["files"][normalized] = ctx.read(_label_for_path(path, known))

    return resolved, solution.get("metadata", {})

def resolve_hubs(ctx, specs):
    """Resolve hubs defined by requirement files.

    Hubs whose inputs equal those of the solution recorded in the lockfile's facts
    are rebuilt from it without running the solver. The others are solved, with
    their recorded solution as the starting point.

    Args:
        ctx (module_ctx): The extension context.
        specs (dict[str, struct]): `resolve_spec`s keyed by hub name.

    Returns:
        struct: With `locks`, hub name to a list of `(platform, packages)` pairs
            where `packages` has the shape `parse_lockfile` returns, and `facts`,
            what to record for the next evaluation.
    """
    upgrade = _upgrade(ctx)
    inputs = {name: _hub_inputs(ctx, spec) for name, spec in specs.items()}
    recorded = {}
    facts = {}
    resolved = {}
    to_solve = {}
    for name, spec in specs.items():
        previous = _recorded_solution(ctx, spec)
        if previous != None:
            recorded[name] = previous
        if previous != None and upgrade == None and _unchanged(ctx, spec, previous, inputs[name]):
            resolved[name] = previous["locks"]
            facts["solution:" + name] = previous["raw"]
            facts.update(_recorded_metadata(ctx, previous["locks"]))
        else:
            to_solve[name] = spec

    if to_solve:
        require_wasm(ctx, to_solve.keys())
        groups = {}
        for spec in to_solve.values():
            groups.setdefault(_solver_id(spec), []).append(spec)
        for group in groups.values():
            locks, texts = _resolve_group(
                ctx,
                sorted(group, key = lambda spec: spec.name),
                inputs,
                recorded,
                upgrade,
            )
            resolved.update(locks)
            for name, hub_locks in locks.items():
                facts["solution:" + name] = dict(
                    _compact_locks(hub_locks, specs[name]),
                    inputs = _recorded_inputs(inputs[name]),
                    schema = FACTS_SCHEMA,
                )
                facts.update(_referenced_metadata(hub_locks, texts))

    return struct(
        facts = facts,
        locks = {
            name: [(platform, locks[platform]) for platform in specs[name].platforms]
            for name, locks in resolved.items()
        },
    )
