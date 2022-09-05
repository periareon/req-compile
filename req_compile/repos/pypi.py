"""Repository to handle pulling packages from online package indexes."""
import enum
import logging
import os
import re
import sys
import time
import urllib
import urllib.parse
import warnings
from functools import lru_cache
from hashlib import sha256
from html.parser import HTMLParser
from typing import Any, List, Optional, Sequence, Tuple

import pkg_resources
import requests
from overrides import overrides

from req_compile.containers import RequirementContainer
from req_compile.errors import MetadataError
from req_compile.metadata import extract_metadata
from req_compile.repos.repository import Candidate, Repository, filename_to_candidate

LOG = logging.getLogger("req_compile.repository.pypi")


SYS_PY_VERSION = pkg_resources.parse_version(
    sys.version.split(" ", 1)[0].replace("+", "")
)
SYS_PY_MAJOR = pkg_resources.parse_version("{}".format(sys.version_info.major))
SYS_PY_MAJOR_MINOR = pkg_resources.parse_version(
    "{}.{}".format(sys.version_info.major, sys.version_info.minor)
)

OPS = {
    "<": lambda x, y: x < y,
    ">": lambda x, y: x > y,
    "==": lambda x, y: x == y,
    "!=": lambda x, y: x != y,
    ">=": lambda x, y: x >= y,
    "<=": lambda x, y: x <= y,
}


def check_python_compatibility(requires_python: str) -> bool:
    if requires_python is None:
        return True
    try:
        return all(
            _check_py_constraint(part)
            for part in requires_python.split(",")
            if part.strip()
        )
    except ValueError:
        raise ValueError(
            "Unable to parse requires python expression: {}".format(requires_python)
        )


def _check_py_constraint(version_constraint: str) -> bool:
    ref_version = SYS_PY_VERSION

    version_part = re.split("[!=<>~]", version_constraint)[-1].strip()
    operator = version_constraint.replace(version_part, "").strip()
    if version_part and not operator:
        operator = "=="

    dotted_parts = len(version_part.split("."))
    if version_part.endswith(".*"):
        version_part = version_part.replace(".*", "")
        if dotted_parts == 3:
            ref_version = SYS_PY_MAJOR_MINOR
        elif dotted_parts == 2:
            ref_version = SYS_PY_MAJOR
    else:
        if dotted_parts == 2:
            ref_version = SYS_PY_MAJOR_MINOR
        elif dotted_parts == 1:
            ref_version = SYS_PY_MAJOR_MINOR
            version_part += ".0"

    version = pkg_resources.parse_version(version_part)
    if operator == "~=":
        # Convert ~= to the >=, < equivalent check
        # See: https://packaging.python.org/guides/distributing-packages-using-setuptools/#python-requires
        major_num = int(str(version_part).split(".", maxsplit=1)[0])
        equivalent_check = ">={},<{}".format(version_part, major_num + 1)
        return check_python_compatibility(equivalent_check)
    try:
        return OPS[operator](ref_version, version)
    except KeyError:
        raise ValueError("Unable to parse constraint {}".format(version_constraint))


class LinksHTMLParser(HTMLParser):
    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url
        self.dists: List[Candidate] = []
        self.active_link: Optional[Tuple[str, Optional[str]]] = None
        self.active_skip = False
        warnings.filterwarnings(
            "ignore", category=pkg_resources.PkgResourcesDeprecationWarning  # type: ignore[attr-defined]
        )

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.active_link = None
        if tag == "a":
            self.active_skip = False
            requires_python = None
            for attr in attrs:
                if attr[0] == "href":
                    self.active_link = self.url, attr[1]
                elif (
                    attr[0] == "metadata-requires-python"
                    or attr[0] == "data-requires-python"
                ):
                    requires_python = attr[1]

            if requires_python:
                try:
                    self.active_skip = not check_python_compatibility(requires_python)
                except ValueError:
                    LOG.error(
                        'Failed to parse requires expression "%s" for requirement %s',
                        requires_python,
                        self.active_link,
                    )

    def handle_data(self, data: str) -> None:
        if self.active_link is None or self.active_skip:
            return
        candidate = filename_to_candidate(self.active_link, data)
        if candidate is not None:
            self.dists.append(candidate)

    def error(self, message: str) -> None:
        raise RuntimeError(message)


def normalize(name: str) -> str:
    """Normalize per PEP-0503."""
    return re.sub(r"(\s|[-_.])+", "-", name).lower()


@lru_cache(maxsize=None)
def _scan_page_links(
    index_url: str, project_name: str, session: requests.Session, retries: int
) -> Sequence[Candidate]:
    """Scan a Python index's HTML page for links for a given project.

    Args:
        index_url: Base index URL to request from.
        project_name: From to fetch candidates for.
        session: Open requests session.
        retries: Numer of times to retry.

    Returns:
        Candidates on this index's page.
    """

    url = "{index_url}/{project_name}".format(
        index_url=index_url, project_name=normalize(project_name)
    )
    LOG.info("Fetching versions for %s from %s", project_name, url)
    if session is None:
        session = requests
    response = session.get(url + "/")

    if retries and 500 <= response.status_code < 600:
        time.sleep(0.1)
        return _scan_page_links(index_url, project_name, session, retries - 1)

    # Raise for any error status that's not 404
    if response.status_code != 404:
        response.raise_for_status()

    parser = LinksHTMLParser(response.url)
    parser.feed(response.content.decode("utf-8"))

    return parser.dists


def _do_download(
    logger: logging.Logger,
    filename: str,
    link: Tuple[str, str],
    session: requests.Session,
    wheeldir: str,
) -> Tuple[str, bool]:
    url, resource = link
    split_link = resource.split("#sha256=")
    if len(split_link) > 1:
        sha = split_link[1]
    else:
        sha = None

    output_file = os.path.join(wheeldir, filename)

    if sha is not None and os.path.exists(output_file):
        hasher = sha256()
        with open(output_file, "rb") as handle:
            while True:
                block = handle.read(4096)
                if not block:
                    break
                hasher.update(block)
        if hasher.hexdigest() == sha:
            logger.info("Reusing %s", output_file)
            return output_file, True
        logger.debug("No hash match for downloaded file, removing")
        os.remove(output_file)
    else:
        logger.debug("No file in wheel-dir")

    full_link = urllib.parse.urljoin(url, resource)
    logger.info("Downloading %s -> %s", full_link, output_file)
    if session is None:
        session = requests
    response = session.get(full_link, stream=True)

    with open(output_file, "wb") as handle:
        for block in response.iter_content(4 * 1024):
            handle.write(block)
    return output_file, False


class IndexType(enum.Enum):
    DEFAULT = 0
    INDEX_URL = 1
    EXTRA_INDEX_URL = 2


class PyPIRepository(Repository):
    """A repository that conforms to the PEP standard for webpage index of python distributions."""

    def __init__(
        self,
        index_url: str,
        wheeldir: str,
        allow_prerelease: bool = False,
        retries: int = 3,
        index_type: IndexType = IndexType.INDEX_URL,
    ) -> None:
        """Constructor.

        Args:
            index_url (str): URL of the base index
            wheeldir (str): Directory to download wheels and source dists to, if required
            allow_prerelease (bool, optional): Whether to consider prereleases
            retries (int): Number of times to retry. A value of 0 will never retry
            index_type: Type of PyPI repository this is, e.g. --extra-index-url.
        """
        super().__init__("pypi", allow_prerelease)

        if index_url.endswith("/"):
            index_url = index_url[:-1]
        self.index_url = index_url
        if wheeldir is not None:
            self.wheeldir = os.path.abspath(wheeldir)
        else:
            self.wheeldir = None
        self.allow_prerelease = allow_prerelease
        self.retries = retries
        self.index_type = index_type

        self.session = requests.Session()

    def __repr__(self) -> str:
        if self.index_type == IndexType.DEFAULT:
            return f"<default index> {self.index_url}"
        elif self.index_type == IndexType.INDEX_URL:
            return f"--index-url {self.index_url}"
        elif self.index_type == IndexType.EXTRA_INDEX_URL:
            return f"--extra-index-url {self.index_url}"
        raise ValueError("Unknown url type")

    def __eq__(self, other: Any) -> bool:
        return (
            isinstance(other, PyPIRepository)
            and super(PyPIRepository, self).__eq__(other)
            and self.index_url == other.index_url
        )

    def __hash__(self) -> int:
        return hash("pypi") ^ hash(self.index_url)

    @overrides
    def get_candidates(
        self, req: Optional[pkg_resources.Requirement]
    ) -> Sequence[Candidate]:
        if req is None:
            return []
        return _scan_page_links(
            self.index_url, req.project_name, self.session, self.retries
        )

    @overrides
    def resolve_candidate(
        self, candidate: Candidate
    ) -> Tuple[RequirementContainer, bool]:
        filename, cached = None, True
        try:
            # In this repository type, filename is always provided.
            if candidate.filename is None:
                raise ValueError("Could not find the local filename to download to.")

            filename, cached = _do_download(
                self.logger,
                candidate.filename,
                candidate.link,
                self.session,
                self.wheeldir,
            )
            dist_info = extract_metadata(filename, origin=self)
            _, resource = candidate.link
            if "#" in resource:
                _, _, hash_pair = resource.partition("#")
                dist_info.hash = hash_pair.replace("=", ":")
            return dist_info, cached
        except MetadataError:
            if not cached and filename is not None:
                try:
                    os.remove(filename)
                except EnvironmentError:
                    pass
            raise

    @overrides
    def close(self) -> None:
        self.session.close()
