"""The errors the solver raises about pinned hashes, beyond req-compile's own."""

from typing import Dict, List, Set

import packaging.version


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


class PinNotUsed(Exception):
    """The pinned file names a version, with hashes, that the solution does not use.

    Raised after a solve when the requirements still allow the pinned version, so
    the solver moved away from it only because no artifact of it the platform can
    use carries one of the pinned hashes: a bump with a wrong hash, or one to a
    release without a wheel for the platform. Resolving quietly to another version
    would hide exactly what the pin was meant to say.
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        name: str,
        version: packaging.version.Version,
        chosen: packaging.version.Version,
        target: str,
        hashes: Set[str],
        offers: List[str],
    ) -> None:
        self.offers = len(offers)
        super().__init__(
            "`{name}` is pinned to {version} in the hub's requirements file but the hub "
            "resolved {chosen} for {target}: no artifact of {version} the platform can "
            "use matches the --hash values pinned for it ({hashes}). The index offers: "
            "{offers}.".format(
                name=name,
                version=version,
                chosen=chosen,
                target=target,
                hashes=", ".join(sorted(value[:12] for value in hashes)),
                offers=", ".join(offers) or "nothing of that version",
            )
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
