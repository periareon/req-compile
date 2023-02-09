import itertools
from typing import Any, Iterable, Iterator, List, Optional, Tuple

import packaging.requirements
import packaging.version
import pkg_resources

from req_compile.utils import reduce_requirements, req_iter_from_file


def req_uses_extra(req: pkg_resources.Requirement, extra: Optional[str]) -> bool:
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
        reqs: Iterable[pkg_resources.Requirement],
        meta: bool = False,
    ) -> None:
        self.name = name
        self.reqs = list(reqs) if reqs else []
        # Store setup requirements for use when populating a wheeldir.
        self.setup_reqs: List[pkg_resources.Requirement] = []
        self.origin: Any = None
        self.meta = meta
        self.version: Optional[packaging.version.Version] = None
        self.hash: Optional[str] = None
        self.candidate: Any = None

    def __iter__(self) -> Iterator[pkg_resources.Requirement]:
        return iter(self.reqs)

    def requires(self, extra=None):
        # type: (str) -> Iterable[pkg_resources.Requirement]
        return reduce_requirements(
            req for req in self.reqs if req_uses_extra(req, extra)
        )

    def to_definition(
        self, extras: Optional[Iterable[str]]
    ) -> Tuple[str, Optional[packaging.version.Version]]:
        raise NotImplementedError()


def reqs_from_files(
    requirements_files: Iterable[str], parameters: List[str] = None
) -> Iterable[pkg_resources.Requirement]:
    """Produce a list of requirements from multiple requirements files.

    Args:
        requirements_files: Paths to requirements files to load.
        parameters: Container gathering all extra parameters in the files.

    Returns:
        Iterable of requirements in order loaded from the given requirements files.
    """
    if parameters is None:
        parameters = []
    raw_reqs: Iterable[pkg_resources.Requirement] = iter([])
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
        reqs: Iterable[pkg_resources.Requirement],
        parameters: List[str] = None,
        **_kwargs: Any
    ) -> None:
        super(RequirementsFile, self).__init__(filename, reqs, meta=True)
        self.parameters = parameters

    def __repr__(self):
        # type: () -> str
        return "RequirementsFile({})".format(self.name)

    @classmethod
    def from_file(cls, full_path, **kwargs):
        # type: (str, **Any) -> RequirementsFile
        """Load requirements from a file and build a RequirementsFile

        Args:
            full_path (str): The path to the file to load

        Keyword Args:
            Additional arguments to forward to the class constructor
        """
        parameters: List[str] = []
        reqs = reqs_from_files([full_path], parameters=parameters)
        return cls(full_path, reqs, parameters=parameters, **kwargs)

    def __str__(self) -> str:
        return self.name

    def to_definition(self, extras):
        # type: (Optional[Iterable[str]]) -> Tuple[str, Optional[packaging.version.Version]]
        return self.name, None


class DistInfo(RequirementContainer):
    """Metadata describing a distribution of a project"""

    def __init__(self, name, version, reqs, meta=False):
        # type: (str, Optional[packaging.version.Version], Iterable[pkg_resources.Requirement], bool) -> None
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

    def __str__(self):
        # type: () -> str
        return "{}=={}".format(*self.to_definition(None))

    def to_definition(self, extras):
        # type: (Optional[Iterable[str]]) -> Tuple[str, Optional[packaging.version.Version]]
        req_expr = "{}{}".format(
            self.name, ("[" + ",".join(sorted(extras)) + "]") if extras else ""
        )
        return req_expr, self.version

    def __repr__(self):
        # type: () -> str
        return (
            self.name
            + " "
            + str(self.version)
            + "\n"
            + "\n".join([str(req) for req in self.reqs])
        )


class PkgResourcesDistInfo(RequirementContainer):
    def __init__(self, dist: pkg_resources.Distribution) -> None:
        """
        Args:
            dist: The distribution to wrap
        """
        super(PkgResourcesDistInfo, self).__init__(dist.project_name, [])
        self.dist = dist
        self.version = dist.parsed_version

    def __str__(self) -> str:
        return "{}=={}".format(*self.to_definition(None))

    def requires(self, extra: str = None) -> Iterable[pkg_resources.Requirement]:
        return self.dist.requires(extras=(extra,) if extra else ())

    def to_definition(
        self, extras: Optional[Iterable[str]]
    ) -> Tuple[str, Optional[packaging.version.Version]]:
        req_expr = "{}{}".format(
            self.dist.project_name,
            ("[" + ",".join(sorted(extras)) + "]") if extras else "",
        )
        return req_expr, self.version
