import collections
import logging
import os
import shutil
import tempfile
from six.moves import urllib
from six.moves import html_parser

import pkg_resources
import requests
from hashlib import sha256
try:
    from functools32 import lru_cache
except ModuleNotFoundError:
    from functools import lru_cache

Candidate = collections.namedtuple('Candidate', 'name filename version py_version link')


logger = logging.getLogger('qer.pypi')


@lru_cache()
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

    class LinksHTMLParser(html_parser.HTMLParser):
        def __init__(self, url):
            super(LinksHTMLParser, self).__init__()
            self.url = url
            self.dists = []
            self.active_link = None

        def handle_starttag(self, tag, attrs):
            if tag == 'a':
                for attr in attrs:
                    if attr[0] == 'href':
                        self.active_link = urllib.parse.urljoin(self.url, attr[1])
                        break

        def handle_data(self, filename):
            extensions = ('.whl', '.tar.gz', '.tgz', '.zip')
            if '.whl' in filename:
                data_parts = filename.split('-')
                name = data_parts[0]
                version = pkg_resources.parse_version(data_parts[1])
                abi = data_parts[3]
                platform = data_parts[4].split('.')[0]
                if platform == 'any' or platform == 'win_amd64':
                    self.dists.insert(0, Candidate(name,
                                                   filename,
                                                   version,
                                                   tuple(data_parts[2].split('.')),
                                                   self.active_link))
            elif '.tar.gz' in filename or '.tgz' in filename or '.zip' in filename:
                data_parts = filename.split('-')
                name = data_parts[0]
                version_text = data_parts[-1]
                for ext in extensions:
                    version_text = version_text.replace(ext, '')
                version = pkg_resources.parse_version(version_text)
                self.dists.insert(0, Candidate(name, filename, version, (), self.active_link))

    parser = LinksHTMLParser(response.url)
    parser.feed(response.content.decode('utf-8'))

    return sorted(parser.dists, key=lambda x: x.version, reverse=True)


def _do_download(index_url, filename, link, session, wheeldir):
    split_link = link.split('#sha256=')
    sha = split_link[1]

    output_file = os.path.join(wheeldir, filename)

    if os.path.exists(output_file):
        hasher = sha256()
        with open(output_file, 'rb') as handle:
            while True:
                block = handle.read(1024)
                if not block:
                    break
                hasher.update(block)
        if hasher.hexdigest() == sha:
            logger.info('Reusing %s', output_file)
            return output_file, True

        print("File hash doesn't match")

    full_link = split_link[0]
    logging.getLogger('qer.net.pypi').info('Downloading %s -> %s', full_link, output_file)
    if session is None:
        session = requests
    response = session.get(full_link, stream=True)

    with open(output_file, 'wb') as handle:
        for block in response.iter_content(4 * 1024):
            handle.write(block)
    return output_file, False


class NoCandidateException(Exception):
    def __init__(self, *args):
        super(NoCandidateException, self).__init__(*args)
        self.project_name = None
        self.specifier = None

    def __str__(self):
        return 'NoCandidateException - no candidate for "{}" satisfies {}'.format(
            self.project_name,
            self.specifier
        )


def start_session():
    return requests.Session()


def download_candidate(project_name, py_ver='py2', specifier=None, allow_prerelease=False,
                       index_url=None, skip_source=True, session=None, wheeldir=None):
    logger = logging.getLogger('qer.download')
    logger.info('Downloading %s, with constraints %s', project_name, specifier)
    if index_url is None:
        index_url = 'https://pypi.org/simple'
    candidates = _scan_page_links(index_url, project_name, session)

    delete_wheeldir = False
    if wheeldir is None:
        wheeldir = tempfile.mkdtemp()
        delete_wheeldir = True

    for candidate in candidates:
        if not ('py2' in candidate.py_version or 'cp27' in candidate.py_version) and skip_source:
            continue

        has_equality = any(spec.operator == '==' for spec in specifier)

        if not has_equality and not allow_prerelease and candidate.version.is_prerelease:
            continue

        if specifier is not None and not specifier.contains(candidate.version):
            continue

        return _do_download(index_url, candidate.filename, candidate.link, session, wheeldir)

    if not skip_source:
        ex = NoCandidateException()
        ex.project_name = project_name
        ex.specifier = specifier
        raise ex

    return download_candidate(project_name, py_ver=py_ver, specifier=specifier,
                              allow_prerelease=allow_prerelease, index_url=index_url,
                              skip_source=False, session=session, wheeldir=wheeldir)
