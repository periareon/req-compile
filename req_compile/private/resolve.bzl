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
of every distribution it consulted. A hub whose inputs did not change is rebuilt
from its recorded solution without loading the solver. A hub whose inputs changed
is re-solved with the recorded versions as soft pins and the recorded metadata on
hand, so only what the change touches is fetched. `REQ_COMPILE_UPGRADE=all` (or a
comma separated list of packages) drops the pins.

Nothing here runs unless a hub asks for it, and then only when Bazel's
WebAssembly support is enabled; see `require_wasm`.
"""

load("@bazel_tools//tools/build_defs/repo:utils.bzl", "read_user_netrc", "use_netrc")
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
        solver,
        constraints = [],
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
        solver (Label): The WebAssembly solver module.
        constraints (list[Label]): Constraint files, never themselves installed.
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
    parts = normalized[len(INPUT_ROOT) + 1:].split("/")
    if len(parts) < 2:
        fail("The solver asked for a file it cannot name: {}".format(path))
    repo = "" if parts[0] == "_main" else parts[0]
    return Label("@@{}//{}:{}".format(repo, "/".join(parts[1:-1]), parts[-1]))

def _run(ctx, module, spec, payload):
    result = ctx.execute_wasm(
        module,
        "solve",
        input = json.encode(payload),
        timeout = spec.timeout,
        memory_limit = spec.memory_limit,
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

    # The whole wheel was downloaded. Extract it and read its METADATA.
    ctx.extract(path, output = path + ".d", type = "zip")
    for entry in ctx.path(path + ".d").readdir():
        if entry.basename.endswith(".dist-info"):
            return ctx.read(entry.get_child("METADATA"))
    fail("No `.dist-info/METADATA` in {}".format(request["url"]))

def _lock_packages(packages):
    """Convert the solver's packages into the structure `parse_lockfile` produces.

    `filename` and `core_metadata` are kept beyond what a lock file records: a
    later evaluation hands them back to the solver, which uses them to stand in
    for the index page of a package it does not need to change.
    """
    result = {}
    for data in packages.values():
        result[sanitize_package_name(data["package"])] = {
            "annotations": {},
            "constraint": None,
            "core_metadata": data.get("core_metadata", False),
            "deps": sorted([sanitize_package_name(dep) for dep in data["deps"]]),
            "filename": data.get("filename", ""),
            "hash_pinned": data.get("hash_pinned", False),
            "package": data["package"],
            "sha256": data["sha256"],
            "url": data["url"],
            "version": data["version"],
            "via": data.get("via"),
            "whl": None,
        }
    return result

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
            "enforce_hashes": spec.enforce_hashes,
            "index_urls": spec.index_urls,
            "platforms": spec.platforms,
            "python_version": spec.python_version,
        },
        "files": {
            _input_path(label): ctx.read(label)
            for label in spec.requirements_in + spec.constraints
        },
    }

def _thaw(value):
    """A mutable deep copy of a value read from the lockfile's facts, which are frozen."""
    return json.decode(json.encode(value))

# Keys of a package whose value may be `None`. The lockfile omits null values,
# so they are restored when a recorded solution is read back.
_OPTIONAL_PACKAGE_KEYS = {
    "annotations": {},
    "constraint": None,
    "via": None,
    "whl": None,
}

def _recorded_solution(ctx, spec):
    """The solution a previous evaluation recorded for a hub, if it is usable."""
    recorded = _fact(ctx, "solution:" + spec.name)
    if type(recorded) != "dict" or recorded.get("schema") != FACTS_SCHEMA:
        return None
    if sorted(recorded.get("locks", {}).keys()) != sorted(spec.platforms):
        return None
    recorded = _thaw(recorded)
    for packages in recorded["locks"].values():
        for data in packages.values():
            for key, default in _OPTIONAL_PACKAGE_KEYS.items():
                data.setdefault(key, _thaw(default))
    return recorded

def _recorded_metadata(ctx, locks):
    """The metadata facts of every distribution of recorded locks."""
    facts = {}
    for packages in locks.values():
        for data in packages.values():
            if not data.get("sha256"):
                continue
            key = "meta:" + data["sha256"]
            fact = _fact(ctx, key)
            if fact != None:
                facts[key] = _thaw(fact)
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
            url = request["url"] + ".metadata"
            sha256 = core["sha256"] if type(core) == "dict" else ""
        else:
            path = "req_compile_resolve/{}.whl".format(scratch)
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

def _document(ctx, request, path):
    """The document to hand the solver for a download that succeeded."""
    if request["op"] == "fetch":
        return {"body": ctx.read(path), "kind": "index", "url": request["url"]}
    return {
        "body": _metadata_text(ctx, request, path),
        "kind": "metadata",
        "url": request["url"],
    }

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
        tuple: The resolved hubs and the facts the solver consulted.
    """
    first = specs[0]
    module = ctx.load_wasm(ctx.path(first.solver))
    netrc = read_user_netrc(ctx)

    known = {}
    hubs = {}
    facts = {}
    for spec in specs:
        for label in spec.requirements_in + spec.constraints:
            known[_input_path(label)] = label
        hubs[spec.name] = {
            "allow_prerelease": spec.allow_prerelease,
            "allow_sdists": spec.allow_sdists,
            "constraints": [_input_path(label) for label in spec.constraints],
            "enforce_hashes": spec.enforce_hashes,
            "indexes": spec.index_urls,
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
            facts.update(_recorded_metadata(ctx, previous["locks"]))

    documents = {}
    solution = None
    scratch = 0
    for round_number in range(1, first.max_rounds + 1):
        ctx.report_progress("Resolving {}: round {} ({} facts)".format(
            ", ".join(sorted(hubs)),
            round_number,
            len(facts),
        ))
        out = _run(ctx, module, first, {
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
            # whose download failed. Fetch those again, strictly: a network
            # failure then surfaces as Bazel's own download error, which is not
            # cached as a resolution failure the way a `fail()` is, and a page
            # that does not exist is reported with its URL. When every fetch
            # succeeds the solve goes on with the documents.
            retry = out.get("retry", [])
            if not retry:
                fail("Failed to resolve the requirements of hub `{}`: {}".format(out.get("hub", "?"), out["message"]))
            for request in retry:
                scratch += 1
                request, path, _ = _start_download(ctx, netrc, request, scratch, allow_fail = False, block = True)
                facts.pop(request["id"], None)
                documents[request["id"]] = _document(ctx, request, path)
            continue

        pending = []
        for request in out["requests"]:
            if request["op"] == "read":
                facts[request["id"]] = {"text": ctx.read(_label_for_path(request["path"], known))}
                continue

            if request["op"] == "metadata" and request["sha256"]:
                cached = _fact(ctx, "meta:" + request["sha256"])
                if cached != None:
                    facts[request["id"]] = _thaw(cached)
                    continue

            scratch += 1
            pending.append(_start_download(ctx, netrc, request, scratch, allow_fail = True))

        for request, path, token in pending:
            if token.wait().success:
                documents[request["id"]] = _document(ctx, request, path)
            else:
                facts[request["id"]] = {"error": "download failed: {}".format(request["url"])}

    if solution == None:
        fail("Resolving {} did not converge in {} rounds. Raise `max_rounds` if the dependency graph is unusually deep.".format(
            ", ".join(sorted(hubs)),
            first.max_rounds,
        ))

    resolved = {}
    for spec in specs:
        locks = solution["hubs"][spec.name]["locks"]
        resolved[spec.name] = {
            platform: _lock_packages(locks[platform]["packages"])
            for platform in spec.platforms
        }

    consulted = {}
    for sha256 in solution.get("consulted", []):
        fact = facts.get("meta:" + sha256)
        if fact != None and "error" not in fact:
            consulted["meta:" + sha256] = fact
    return resolved, consulted

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
        if previous != None and upgrade == None and previous["inputs"] == inputs[name]:
            resolved[name] = previous["locks"]
            facts["solution:" + name] = previous
            facts.update(_recorded_metadata(ctx, previous["locks"]))
        else:
            to_solve[name] = spec

    if to_solve:
        require_wasm(ctx, to_solve.keys())
        groups = {}
        for spec in to_solve.values():
            groups.setdefault(str(spec.solver), []).append(spec)
        for group in groups.values():
            locks, consulted = _resolve_group(
                ctx,
                sorted(group, key = lambda spec: spec.name),
                inputs,
                recorded,
                upgrade,
            )
            resolved.update(locks)
            facts.update(consulted)
            for name, hub_locks in locks.items():
                facts["solution:" + name] = {
                    "inputs": inputs[name],
                    "locks": hub_locks,
                    "schema": FACTS_SCHEMA,
                }

    return struct(
        facts = facts,
        locks = {
            name: [(platform, locks[platform]) for platform in specs[name].platforms]
            for name, locks in resolved.items()
        },
    )
