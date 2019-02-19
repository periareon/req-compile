import collections
import logging
import os
import shutil
import sys
import tempfile
import platform

import six
from six.moves import urllib
from six.moves import html_parser

import pkg_resources
import requests
from hashlib import sha256

from qer import utils

try:
    from functools32 import lru_cache
except ImportError:
    from functools import lru_cache

EXTENSIONS = ('.whl', '.tar.gz', '.tgz', '.zip')
Candidate = collections.namedtuple('Candidate', 'name filename version py_version platform link')


INTERPRETER_TAGS = {
    'CPython': 'cp',
    'IronPython': 'ip',
    'PyPy': 'pp',
    'Jython': 'jy',
}
INTERPRETER_TAG = INTERPRETER_TAGS.get(platform.python_implementation(), 'cp')

PY_VERSION_NUM = str(sys.version_info.major) + str(sys.version_info.minor)

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


class NoCandidateException(Exception):
    def __init__(self, *args):
        super(NoCandidateException, self).__init__(*args)
        self.project_name = None
        self.specifier = None
        self.results = None
        self.constraint_results = None
        self.mapping = None

    def __str__(self):
        return 'NoCandidateException - no candidate for "{}" satisfies {}'.format(
            self.project_name,
            self.specifier
        )


def start_session():
    return requests.Session()


def _check_py_compatibility(py_version):
    # https://www.python.org/dev/peps/pep-0425/
    if py_version == ():
        return True

    compatible_versions = []
    if six.PY2:
        compatible_versions.append('py2')
    else:
        compatible_versions.append('py3')

    compatible_versions.append(INTERPRETER_TAG + PY_VERSION_NUM)

    if not any(version in compatible_versions for version in py_version):
        return False

    return True


def _check_platform_compatibility(py_platform):
    if py_platform == 'any':
        return True

    tag = None
    if sys.platform == 'win32':
        if platform.machine() == 'AMD64':
            tag = 'win_amd64'
        else:
            tag = 'win32'
    elif sys.platform == 'linux2':
        if platform.machine() == 'x86_64':
            tag = 'manylinux1_x86_64'
        else:
            tag = 'manylinux1_' + platform.machine()

    return py_platform.lower() == tag


def download_candidate(project_name, specifier=None, allow_prerelease=False,
                       index_url=None, skip_source=True, session=None, wheeldir=None):
    logger = logging.getLogger('qer.download')
    logger.info('Downloading %s, with constraints %s', project_name, specifier)
    if index_url is None:
        index_url = 'https://pypi.org/simple'
    candidates = _scan_page_links(index_url, project_name, session)
    has_equality = any(spec.operator == '==' for spec in specifier)

    for candidate in candidates:
        if skip_source and not candidate.filename.endswith('.whl'):
            continue

        if not _check_py_compatibility(candidate.py_version):
            continue

        if not _check_platform_compatibility(candidate.platform):
            continue

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

    return download_candidate(project_name, specifier=specifier,
                              allow_prerelease=allow_prerelease, index_url=index_url,
                              skip_source=False, session=session, wheeldir=wheeldir)
