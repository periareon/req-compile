import collections
import logging
import os
import platform
import sys
from hashlib import sha256

import pkg_resources
import requests
import six
from six.moves import html_parser
from six.moves import urllib

from qer.repository import Repository, NoCandidateException, Candidate

try:
    from functools32 import lru_cache
except ImportError:
    from functools import lru_cache

EXTENSIONS = ('.whl', '.tar.gz', '.tgz', '.zip')

logger = logging.getLogger('qer.pypi')


class LinksHTMLParser(html_parser.HTMLParser):
    def __init__(self, url):
        html_parser.HTMLParser.__init__(self)
        self.url = url
        self.dists = []
        self.active_link = None

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            for attr in attrs:
                if attr[0] == 'href':
                    self.active_link = self.url, attr[1]
                    break

    def handle_data(self, filename):
        candidate = None
        if '.whl' in filename:
            candidate = _wheel_candidate(self.active_link, filename)
        elif '.tar.gz' in filename or '.tgz' in filename or '.zip' in filename:
            candidate = _tar_gz_candidate(self.active_link, filename)

        if candidate is not None:
            self.dists.insert(0, candidate)


def _wheel_candidate(active_link, filename):
    data_parts = filename.split('-')
    name = data_parts[0]
    version = pkg_resources.parse_version(data_parts[1])
    platform = data_parts[4].split('.')[0]
    return Candidate(name,
                     filename,
                     version,
                     tuple(data_parts[2].split('.')),
                     platform,
                     active_link)


def _tar_gz_candidate(active_link, filename):
    data_parts = filename.split('-')
    version_idx = -1
    for idx, part in enumerate(data_parts):
        if part[0].isdigit() and '.' in part:
            version_idx = idx
            break

    name = '-'.join(data_parts[:version_idx])
    version_text = data_parts[version_idx]
    for ext in EXTENSIONS:
        version_text = version_text.replace(ext, '')

    version = pkg_resources.parse_version(version_text)
    return Candidate(name, filename, version, (), 'any', active_link)


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

    return sorted(parser.dists, key=lambda x: x.version, reverse=True)


def _do_download(index_url, filename, link, session, wheeldir):
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

        print("File hash doesn't match")

    full_link = urllib.parse.urljoin(url, link)
    logging.getLogger('qer.net.pypi').info('Downloading %s -> %s', full_link, output_file)
    if session is None:
        session = requests
    response = session.get(full_link, stream=True)

    with open(output_file, 'wb') as handle:
        for block in response.iter_content(4 * 1024):
            handle.write(block)
    return output_file, False


class PyPIRepository(Repository):
    def __init__(self, index_url, wheeldir, allow_prerelease=None):
        super(PyPIRepository, self).__init__(allow_prerelease)

        self.index_url = index_url
        self.wheeldir = wheeldir
        self.allow_prerelease = allow_prerelease

        self._logger = logging.getLogger('qer.pypi')
        self.session = requests.Session()

    def __repr__(self):
        return 'PyPIRepository({})'.format(self.index_url)

    @property
    def logger(self):
        return self._logger

    def get_candidates(self, req):
        return _scan_page_links(self.index_url, req.name, self.session)

    def resolve_candidate(self, candidate):
        return _do_download(self.index_url, candidate.filename,
                            candidate.link, self.session, self.wheeldir)

    def close(self):
        self.session.close()
