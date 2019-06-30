"""Repository to handle pulling packages from online package indexes"""
import logging
import os
from hashlib import sha256

import requests
from six.moves import html_parser
from six.moves import urllib

try:
    from functools32 import lru_cache
except ImportError:
    from functools import lru_cache

from qer.repos.repository import Repository, process_distribution
from qer.metadata import extract_metadata



LOG = logging.getLogger('qer.pypi')


class LinksHTMLParser(html_parser.HTMLParser):
    def __init__(self, url):
        html_parser.HTMLParser.__init__(self)
        self.url = url
        self.dists = []
        self.active_link = None
        self.active_requires_python = None

    def handle_starttag(self, tag, attrs):
        self.active_link = None
        if tag == 'a':
            self.active_requires_python = None
            for attr in attrs:
                if attr[0] == 'href':
                    self.active_link = self.url, attr[1]
                elif attr[0] == 'metadata-requires-python' or attr[0] == 'data-requires-python':
                    self.active_requires_python = attr[1] or None

    def handle_data(self, data):
        if self.active_link is None:
            return
        candidate = process_distribution(self.active_link, data, self.active_requires_python)
        if candidate is not None:
            self.dists.append(candidate)

    def error(self, message):
        raise RuntimeError(message)


@lru_cache(maxsize=None)
def _scan_page_links(index_url, project_name, session):
    """

    Args:
        index_url:
        project_name:
        session (requests.Session): Session

    Returns:
        (list[Candidate])
    """
    url = '{index_url}/{project_name}'.format(index_url=index_url, project_name=project_name)
    logging.getLogger('qer.net.pypi').info('Fetching versions for %s', project_name)
    if session is None:
        session = requests
    response = session.get(url + '/')

    parser = LinksHTMLParser(response.url)
    parser.feed(response.content.decode('utf-8'))

    return parser.dists


def _do_download(logger, filename, link, session, wheeldir):
    url, link = link
    split_link = link.split('#sha256=')
    sha = split_link[1]

    output_file = os.path.join(wheeldir, filename)

    if os.path.exists(output_file):
        hasher = sha256()
        with open(output_file, 'rb') as handle:
            while True:
                block = handle.read(4096)
                if not block:
                    break
                hasher.update(block)
        if hasher.hexdigest() == sha:
            logger.info('Reusing %s', output_file)
            return output_file, True

    full_link = urllib.parse.urljoin(url, link)
    logger.info('Downloading %s -> %s', full_link, output_file)
    if session is None:
        session = requests
    response = session.get(full_link, stream=True)

    with open(output_file, 'wb') as handle:
        for block in response.iter_content(4 * 1024):
            handle.write(block)
    return output_file, False


class PyPIRepository(Repository):
    def __init__(self, index_url, wheeldir, allow_prerelease=False):
        super(PyPIRepository, self).__init__('pypi', allow_prerelease)

        self.index_url = index_url
        self.wheeldir = wheeldir
        self.allow_prerelease = allow_prerelease

        self.session = requests.Session()

    def __repr__(self):
        return '--index-url {}'.format(self.index_url)

    def __eq__(self, other):
        return (isinstance(other, PyPIRepository) and
                super(PyPIRepository, self).__eq__(other) and
                self.index_url == other.index_url)

    def __hash__(self):
        return hash('pypi') ^ hash(self.index_url)

    def get_candidates(self, req):
        if req is None:
            return []
        return _scan_page_links(self.index_url, req.name, self.session)

    def resolve_candidate(self, candidate):
        filename, cached = _do_download(self.logger, candidate.filename, candidate.link, self.session, self.wheeldir)
        return extract_metadata(filename, origin=self), cached

    def close(self):
        self.session.close()
