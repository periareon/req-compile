import os
import shutil

from req_compile import utils
from req_compile.utils import filter_req, reduce_requirements


class RequirementContainer(object):
    """A container for a list of requirements"""

    def __init__(self, name, reqs, meta=False):
        self.name = name
        self.reqs = list(reqs) if reqs else []
        self.origin = None
        self.meta = meta

    def __iter__(self):
        return iter(self.reqs)

    def requires(self, extra=None):
        return reduce_requirements(req for req in self.reqs if filter_req(req, extra))

    def to_definition(self, extras):
        raise NotImplementedError()


class RequirementsFile(RequirementContainer):
    """Represents a requirements file - a text file containing a list of requirements"""

    def __init__(self, filename, reqs, **_kwargs):
        super(RequirementsFile, self).__init__(filename, reqs, meta=True)

    def __repr__(self):
        return "RequirementsFile({})".format(self.name)

    @classmethod
    def from_file(cls, full_path, **kwargs):
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
        return self.name, None


class DistInfo(RequirementContainer):
    """Metadata describing a distribution of a project"""

    def __init__(self, name, version, reqs, meta=False):
        """
        Args:
            name (str): The project name
            version (pkg_resources.Version): Parsed version of the project
            reqs (Iterable): The list of requirements for the project
            meta (bool): Whether or not hte requirement is a meta-requirement
        """
        super(DistInfo, self).__init__(name, reqs, meta=meta)
        self.version = version
        self.source = None

    def __str__(self):
        return "{}=={}".format(*self.to_definition(None))

    def to_definition(self, extras):
        req_expr = "{}{}".format(
            self.name, ("[" + ",".join(sorted(extras)) + "]") if extras else ""
        )
        return req_expr, self.version

    def __repr__(self):
        return (
            self.name
            + " "
            + str(self.version)
            + "\n"
            + "\n".join([str(req) for req in self.reqs])
        )


class PkgResourcesDistInfo(RequirementContainer):
    def __init__(self, dist):
        """
        Args:
            dist (pkg_resources.Distribution): The distribution to wrap
        """
        super(PkgResourcesDistInfo, self).__init__(dist.project_name, None)
        self.dist = dist
        self.version = dist.parsed_version

    def __str__(self):
        return "{}=={}".format(*self.to_definition(None))

    def requires(self, extra=None):
        return self.dist.requires(extras=(extra,) if extra else ())

    def to_definition(self, extras):
        req_expr = "{}{}".format(
            self.dist.project_name,
            ("[" + ",".join(sorted(extras)) + "]") if extras else "",
        )
        return req_expr, self.version

    def __del__(self):
        try:
            shutil.rmtree(os.path.join(self.dist.location, ".."))
        except EnvironmentError:
            pass
