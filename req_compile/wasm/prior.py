"""What a re-resolution starts from: the recorded solution and the pinned file.

A hub may come with the solution a previous evaluation recorded in the lock
file, and with the pinned requirements file it maintains in the workspace. Both
feed the solver soft pins, versions it prefers while the requirements allow them
(see `_file_pinned` in `entry.py` for how the file's hashes bind), and
`REQ_COMPILE_UPGRADE` names the packages left out of both.
"""

from typing import Any, Dict, Optional, Set

import packaging.requirements
import packaging.version

from req_compile import utils
from req_compile.utils import NormName
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
                facts["meta:" + identity] = metadata_fact(decode_text(text))


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
