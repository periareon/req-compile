import itertools
import os
from pathlib import Path
from typing import Any, Iterable, Iterator, List, Optional, Tuple, Union

import packaging.requirements
import packaging.version
from packaging.requirements import InvalidRequirement

from req_compile.utils import reduce_requirements, req_iter_from_file


def req_uses_extra(
    req: packaging.requirements.Requirement, extra: Optional[str]
) -> bool:
    """Determine if this requirement would be used with the given extra.

    If a distribution is requested with one of its extras, this filter will determine
    if the given requirement in its install requirements is provided. All base
    requirements that don't require the extra will also be included.
    """
    if extra and not req.marker:
        return False
    keep_req = True
    if req.marker:
        extras = {"extra": ""}
        if extra:
            extras = {"extra": extra}
        keep_req = req.marker.evaluate(extras)
    return keep_req


class RequirementContainer:
    """A container for a list of requirements."""

    def __init__(
        self,
        name: str,
        reqs: Iterable[packaging.requirements.Requirement],
        meta: bool = False,
    ) -> None:
        self.name = name
        self.reqs = list(reqs) if reqs else []
        # Store setup requirements for use when populating a wheeldir.
        self.setup_reqs: List[packaging.requirements.Requirement] = []
        self.origin: Any = None
        self.meta = meta
        self.version: Optional[packaging.version.Version] = None
        self.hash: Optional[str] = None
        self.candidate: Any = None

    def __iter__(self) -> Iterator[packaging.requirements.Requirement]:
        return iter(self.reqs)

    def requires(
        self, extra: Optional[str] = None
    ) -> Iterable[packaging.requirements.Requirement]:
        return reduce_requirements(
            req for req in self.reqs if req_uses_extra(req, extra)
        )

    def to_definition(
        self, extras: Optional[Iterable[str]]
    ) -> Tuple[str, Optional[packaging.version.Version]]:
        raise NotImplementedError()


def reqs_from_files(
    requirements_files: Iterable[str], parameters: Optional[List[str]] = None
) -> Iterable[packaging.requirements.Requirement]:
    """Produce a list of requirements from multiple requirements files.

    Args:
        requirements_files: Paths to requirements files to load.
        parameters: Container gathering all extra parameters in the files.

    Returns:
        Iterable of requirements in order loaded from the given requirements files.
    """
    if parameters is None:
        parameters = []
    raw_reqs: Iterable[packaging.requirements.Requirement] = iter([])
    for reqfile_name in requirements_files:
        raw_reqs = itertools.chain(
            raw_reqs, req_iter_from_file(reqfile_name, parameters=parameters)
        )

    return list(raw_reqs)


class RequirementsFile(RequirementContainer):
    """Represents a requirements file - a text file containing a list of requirements"""

    def __init__(
        self,
        filename: str,
        reqs: Iterable[packaging.requirements.Requirement],
        parameters: Optional[List[str]] = None,
        **_kwargs: Any,
    ) -> None:
        super(RequirementsFile, self).__init__(filename, reqs, meta=True)
        self.parameters = parameters

    def __repr__(self) -> str:
        return "RequirementsFile({})".format(self.name)

    @classmethod
    def from_file(
        cls, full_path: Union[str, Path], **kwargs: Any
    ) -> "RequirementsFile":
        """Load requirements from a file and build a RequirementsFile

        Args:
            full_path (str): The path to the file to load

        Keyword Args:
            Additional arguments to forward to the class constructor
        """
        parameters: List[str] = []
        reqs = reqs_from_files([str(full_path)], parameters=parameters)
        return cls(str(full_path), reqs, parameters=parameters, **kwargs)

    def __str__(self) -> str:
        return self.name

    def to_definition(
        self, extras: Optional[Iterable[str]]
    ) -> Tuple[str, Optional[packaging.version.Version]]:
        return self.name, None


class DistInfo(RequirementContainer):
    """Metadata describing a distribution of a project"""

    def __init__(
        self,
        name: str,
        version: Optional[packaging.version.Version],
        reqs: Iterable[packaging.requirements.Requirement],
        meta: bool = False,
    ) -> None:
        """
        Args:
            name: The project name
            version: Parsed version of the project
            reqs: The list of requirements for the project
            meta: Whether or not hte requirement is a meta-requirement
        """
        super(DistInfo, self).__init__(name, reqs, meta=meta)
        self.version = version
        self.source = None

    def __str__(self) -> str:
        return "{}=={}".format(*self.to_definition(None))

    def to_definition(
        self, extras: Optional[Iterable[str]]
    ) -> Tuple[str, Optional[packaging.version.Version]]:
        req_expr = "{}{}".format(
            self.name, ("[" + ",".join(sorted(extras)) + "]") if extras else ""
        )
        return req_expr, self.version

    def __repr__(self) -> str:
        return (
            self.name
            + " "
            + str(self.version)
            + "\n"
            + "\n".join([str(req) for req in self.reqs])
        )


class EggInfoDistInfo(DistInfo):
    """Parse metadata from an .egg-info directory."""

    def __init__(self, egg_info_dir: str, project_name: Optional[str] = None) -> None:
        name = project_name or ""
        version: Optional[packaging.version.Version] = None
        reqs: List[packaging.requirements.Requirement] = []

        pkg_info_path = os.path.join(egg_info_dir, "PKG-INFO")
        if os.path.exists(pkg_info_path):
            import email.parser  # pylint: disable=import-outside-toplevel

            with open(pkg_info_path, "r", encoding="utf-8", errors="replace") as f:
                msg = email.parser.Parser().parse(f)
            name = msg.get("Name", name) or name
            ver_str = msg.get("Version", "")
            if ver_str:
                try:
                    version = packaging.version.Version(ver_str)
                except packaging.version.InvalidVersion:
                    pass

        requires_path = os.path.join(egg_info_dir, "requires.txt")
        if os.path.exists(requires_path):
            reqs = _parse_requires_txt(requires_path)

        super().__init__(name, version, reqs)


def _format_req_str(req: packaging.requirements.Requirement) -> str:
    """Format a Requirement back to a string, preserving extras and URL."""
    extras = "[" + ",".join(sorted(req.extras)) + "]" if req.extras else ""
    if req.url:
        return f"{req.name}{extras} @ {req.url}"
    return f"{req.name}{extras}{req.specifier}"


def _parse_requires_txt(
    requires_path: str,
) -> List[packaging.requirements.Requirement]:
    """Parse an egg-info requires.txt file into a list of requirements.

    Sections like ``[extra_name]`` or ``[extra_name:marker]`` mark subsequent
    requirements as conditional on that extra and/or environment marker.
    """
    reqs: List[packaging.requirements.Requirement] = []
    current_extra: Optional[str] = None
    current_section_marker: Optional[str] = None

    with open(requires_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                # Section headers can be [extra:marker] or [:marker]
                if ":" in section:
                    extra_part, _, marker_part = section.partition(":")
                    current_extra = extra_part.strip() or None
                    current_section_marker = marker_part.strip() or None
                else:
                    current_extra = section
                    current_section_marker = None
                continue
            try:
                req = packaging.requirements.Requirement(line)
            except InvalidRequirement as exc:
                raise InvalidRequirement(
                    f"Failed to parse requirement {line!r} in {requires_path}: {exc}"
                ) from exc
            markers = []
            if req.marker:
                markers.append(str(req.marker))
            if current_extra:
                markers.append(f'extra == "{current_extra}"')
            if current_section_marker:
                markers.append(current_section_marker)
            if markers:
                base = _format_req_str(req)
                combined_marker = " and ".join(markers)
                req = packaging.requirements.Requirement(f"{base}; {combined_marker}")
            reqs.append(req)
    return reqs
