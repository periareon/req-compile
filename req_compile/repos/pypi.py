"""Repository to handle pulling packages from online package indexes"""
import logging
import os
import re
import sys
from hashlib import sha256
from typing import Optional, Sequence, Tuple

import pkg_resources
import requests
from six.moves import html_parser, urllib

from req_compile.containers import RequirementContainer, DistInfo
from req_compile.errors import MetadataError
from req_compile.metadata import extract_metadata
from req_compile.repos.repository import Candidate, Repository, process_distribution

try:
    from functools32 import lru_cache  # type: ignore
except ImportError:
    from functools import lru_cache

LOG = logging.getLogger("req_compile.repository.pypi")


SYS_PY_VERSION = pkg_resources.parse_version(sys.version.split(" ")[0].replace("+", ""))
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


def check_python_compatibility(requires_python):
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


def _check_py_constraint(version_constraint):
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
        major_num = int(str(version_part).split(".")[0])
        equivalent_check = ">={},<{}".format(version_part, major_num + 1)
        return check_python_compatibility(equivalent_check)
    try:
        return OPS[operator](ref_version, version)
    except KeyError:
        raise ValueError("Unable to parse constraint {}".format(version_constraint))


class LinksHTMLParser(html_parser.HTMLParser):
    def __init__(self, url):
        html_parser.HTMLParser.__init__(self)
        self.url = url
        self.dists = []
        self.active_link = None
        self.active_skip = False

    def handle_starttag(self, tag, attrs):
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

    def handle_data(self, data):
        if self.active_link is None or self.active_skip:
            return
        candidate = process_distribution(self.active_link, data)
        if candidate is not None:
            self.dists.append(candidate)

    def error(self, message):
        raise RuntimeError(message)


def normalize(name):
    """Normalize per PEP-0503"""
    return re.sub(r"(\s|[-_.])+", "-", name).lower()


@lru_cache(maxsize=None)
def _scan_page_links(index_url, project_name, session, retries):
    """

    Args:
        index_url:
        project_name:
        session (requests.Session): Session

    Returns:
        (list[Candidate])
    """

    url = "{index_url}/{project_name}".format(
        index_url=index_url, project_name=normalize(project_name)
    )
    LOG.info("Fetching versions for %s from %s", project_name, url)
    if session is None:
        session = requests
    response = session.get(url + "/")

    if retries and 500 <= response.status_code < 600:
        return _scan_page_links(index_url, project_name, session, retries - 1)

    # Raise for any error status that's not 404
    if response.status_code != 404:
        response.raise_for_status()

    parser = LinksHTMLParser(response.url)
    parser.feed(response.content.decode("utf-8"))

    return parser.dists


def _do_download(logger, filename, link, session, wheeldir):
    url, link = link
    split_link = link.split("#sha256=")
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

    full_link = urllib.parse.urljoin(url, link)
    logger.info("Downloading %s -> %s", full_link, output_file)
    if session is None:
        session = requests
    response = session.get(full_link, stream=True)

    with open(output_file, "wb") as handle:
        for block in response.iter_content(4 * 1024):
            handle.write(block)
    return output_file, False


class PyPIRepository(Repository):
    def __init__(self, index_url, wheeldir, allow_prerelease=False, retries=3):
        # type: (str, str, bool, int) -> None
        """
        A repository that conforms to the PEP standard for webpage index of python distributions

        Args:
            index_url (str): URL of the base index
            wheeldir (str): Directory to download wheels and source dists to, if required
            allow_prerelease (bool, optional): Whether or not to consider prereleases
            retries (int): Number of times to retry. A value of 0 will never retry
        """
        super(PyPIRepository, self).__init__("pypi", allow_prerelease)

        if index_url.endswith("/"):
            index_url = index_url[:-1]
        self.index_url = index_url
        if wheeldir is not None:
            self.wheeldir = os.path.abspath(wheeldir)
        else:
            self.wheeldir = None
        self.allow_prerelease = allow_prerelease
        self.retries = retries

        self.session = requests.Session()

    def __repr__(self):
        return "--index-url {}".format(self.index_url)

    def __eq__(self, other):
        return (
            isinstance(other, PyPIRepository)
            and super(PyPIRepository, self).__eq__(other)
            and self.index_url == other.index_url
        )

    def __hash__(self):
        return hash("pypi") ^ hash(self.index_url)

    def get_candidates(self, req):
        # type: (pkg_resources.Requirement) -> Sequence[Candidate]
        if req is None:
            return []
        return _scan_page_links(
            self.index_url, req.project_name, self.session, self.retries
        )

    def resolve_candidate(self, candidate):
        # type: (Candidate) -> Tuple[Optional[RequirementContainer], bool]
        filename, cached = None, True
        try:
            filename, cached = _do_download(
                self.logger,
                candidate.filename,
                candidate.link,
                self.session,
                self.wheeldir,
            )
            return extract_metadata(filename, origin=self), cached
        except MetadataError:
            if not cached and filename is not None:
                try:
                    os.remove(filename)
                except EnvironmentError:
                    pass
            raise

    def close(self):
        # type: () -> None
        self.session.close()
