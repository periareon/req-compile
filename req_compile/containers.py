import os
import shutil
from typing import Any, Iterable, Optional, Tuple

import packaging.version
import pkg_resources

from req_compile import utils
from req_compile.utils import filter_req, reduce_requirements


class RequirementContainer(object):
    """A container for a list of requirements"""

    def __init__(self, name, reqs, meta=False):
        # type: (str, Iterable[pkg_resources.Requirement], bool) -> None
        self.name = name
        self.reqs = list(reqs) if reqs else []
        self.origin = None
        self.meta = meta
        self.version = None  # type: Optional[packaging.version.Version]

    def __iter__(self):
        return iter(self.reqs)

    def requires(self, extra=None):
        # type: (str) -> Iterable[pkg_resources.Requirement]
        return reduce_requirements(req for req in self.reqs if filter_req(req, extra))

    def to_definition(self, extras):
        # type: (Optional[Iterable[str]]) -> Tuple[str, Optional[packaging.version.Version]]
        raise NotImplementedError()


class RequirementsFile(RequirementContainer):
    """Represents a requirements file - a text file containing a list of requirements"""

    def __init__(self, filename, reqs, **_kwargs):
        # type: (str, Iterable[pkg_resources.Requirement], **Any) -> None
        super(RequirementsFile, self).__init__(filename, reqs, meta=True)

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
        reqs = utils.reqs_from_files([full_path])
        return cls(full_path, reqs, **kwargs)

    def __str__(self):
        return self.name

    def to_definition(self, extras):
        # type: (Optional[Iterable[str]]) -> Tuple[str, Optional[packaging.version.Version]]
        return self.name, None


class DistInfo(RequirementContainer):
    """Metadata describing a distribution of a project"""

    def __init__(self, name, version, reqs, meta=False):
        # type: (str, packaging.version.Version, Iterable[pkg_resources.Requirement], bool) -> None
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
    def __init__(self, dist):
        # type: (pkg_resources.Distribution) -> None
        """
        Args:
            dist: The distribution to wrap
        """
        super(PkgResourcesDistInfo, self).__init__(dist.project_name, [])
        self.dist = dist
        self.version = dist.parsed_version  # type: ignore

    def __str__(self):
        # type: () -> str
        return "{}=={}".format(*self.to_definition(None))

    def requires(self, extra=None):
        # type: (str) -> Iterable[pkg_resources.Requirement]
        return self.dist.requires(extras=(extra,) if extra else ())

    def to_definition(self, extras):
        # type: (Optional[Iterable[str]]) -> Tuple[str, Optional[packaging.version.Version]]
        req_expr = "{}{}".format(
            self.dist.project_name,
            ("[" + ",".join(sorted(extras)) + "]") if extras else "",
        )
        return req_expr, self.version

    def __del__(self):
        # type: () -> None
        try:
            shutil.rmtree(os.path.join(self.dist.location, ".."))
        except EnvironmentError:
            pass
