"""What a re-resolution starts from: the recorded solution and the pinned file.

A hub may come with the solution a previous evaluation recorded in the lock
file, and with the pinned requirements file it maintains in the workspace. Both
feed the solver soft pins, versions it prefers while the requirements allow them
(see `_file_pinned` in `entry.py` for how the file's hashes bind), and
`REQ_COMPILE_UPGRADE` names the packages left out of both.
"""

from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import packaging.requirements
import packaging.version

from req_compile import utils
from req_compile.utils import NormName
from req_compile.wasm.errors import PinNotUsed
from req_compile.wasm.files import decode_text
from req_compile.wasm.ingest import metadata_fact


def prior_locks(
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


def link_recorded_metadata(
    prior: Dict[str, Dict[NormName, Dict[str, Any]]], facts: Dict[str, Any]
) -> None:
    """Serve the metadata of recorded distributions from the `md:` facts.

    The lockfile keeps metadata once per distinct text, keyed by its digest, and
    each recorded distribution names the digest of its own; the solver looks
    metadata up by distribution, so the two are joined here.
    """
    for packages in prior.values():
        for entry in packages.values():
            digest = entry.get("metadata")
            identity = entry.get("sha256") or entry.get("url")
            if not digest or not identity or "meta:" + identity in facts:
                continue
            text = facts.get("md:" + digest)
            if isinstance(text, str):
                fact = metadata_fact(decode_text(text))
                # Where the text came from, so that an artifact the pinned file
                # now vouches for gets its metadata read from the wheel itself.
                fact["sidecar"] = bool(entry.get("sidecar"))
                facts["meta:" + identity] = fact


def same_release(
    version: packaging.version.Version, pin: packaging.version.Version
) -> bool:
    """Whether `version` is the release the pin `pin` names.

    A pin without a local segment names every build of that release (`1.0`
    covers `1.0+cpu`), which the pin's hashes then tell apart; a pin with one
    names that build alone.
    """
    if pin.local:
        return version == pin
    return version.public == pin.public


def prior_pins(
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


def exact_version(
    req: packaging.requirements.Requirement,
) -> Optional[packaging.version.Version]:
    """The version a `name==version` line pins, or None for any other line."""
    specs = list(req.specifier)
    if (
        len(specs) != 1
        or specs[0].operator not in ("==", "===")
        or specs[0].version.endswith(".*")
    ):
        return None
    try:
        return packaging.version.Version(specs[0].version)
    except packaging.version.InvalidVersion:
        return None


def upgraded(upgrade: Any) -> Optional[Set[NormName]]:
    """The projects `REQ_COMPILE_UPGRADE` names, or None for all of them."""
    if upgrade == "all":
        return None
    return {utils.normalize_project_name(name) for name in (upgrade or [])}


def _allows(
    req: Optional[packaging.requirements.Requirement],
    version: packaging.version.Version,
) -> bool:
    return req is None or req.specifier.contains(version, prereleases=True)


def check_file_pins(
    hub: Any,
    file_pins: Dict[NormName, Tuple[packaging.version.Version, Set[str]]],
    constraints: Sequence[Any],
    solutions: Sequence[Tuple[Any, Any]],
) -> None:
    """Fail when the solution left a pinned version the requirements still allow.

    The file's version is a soft pin, so the solver may move away from it; that
    is right when `requirements.in`, a constraint or another package's
    requirement excludes the version, and wrong when the only reason was that
    no artifact of the version the platform can use carried one of the file's
    hashes (a bump with a wrong hash, a release without a wheel for a platform,
    another index offering an older release). The solver cannot tell the two
    apart while it resolves, so the solution is checked afterwards against the
    requirements it ended up with: a pinned version every requirement on the
    package still allows must be the one used, with one of its hashes.
    """
    for key, (version, hashes) in file_pins.items():
        if not hashes:
            continue
        if any(
            utils.normalize_project_name(req.name) == key and not _allows(req, version)
            for container in constraints
            for req in getattr(container, "reqs", [])
        ):
            continue
        # Every platform that left the pin; the one with the least to offer for
        # the pinned version is the one to name, since the platforms agree on a
        # version and the poorest page decides for all of them.
        left: List[PinNotUsed] = []
        for target, repos, (solution, _) in zip(hub.targets, hub.indexes, solutions):
            for node in solution:
                meta = node.metadata
                if (
                    node.key != key
                    or meta is None
                    or meta.meta
                    or meta.candidate is None
                    or meta.version is None
                ):
                    continue
                sha256 = ""
                if hasattr(meta.origin, "entry"):  # a FactRepository
                    sha256 = meta.origin.entry(meta.candidate).get("sha256") or ""
                if same_release(meta.version, version) and sha256 in hashes:
                    continue
                if any(
                    not _allows(reverse.dependencies.get(node), version)
                    for reverse in node.reverse_deps
                ):
                    continue
                mismatch = hub.mismatches.get(key)
                if mismatch is not None:
                    raise mismatch
                offers = [
                    offer
                    for repo in repos
                    for offer in repo.artifacts_of(meta.name, version)
                ]
                left.append(
                    PinNotUsed(
                        meta.name, version, meta.version, target.name, hashes, offers
                    )
                )
        if left:
            raise min(left, key=lambda error: error.offers)
