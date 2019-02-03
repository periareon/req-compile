import collections
import logging
import os
from HTMLParser import HTMLParser

import pkg_resources
import requests
from hashlib import sha256
import functools32

Candidate = collections.namedtuple('Candidate', 'name filename version py_version link')


logger = logging.getLogger('qer.pypi')


@functools32.lru_cache()
def _scan_page_links(index_url, project_name):
    """

    Args:
        index_url:
        project_name:

    Returns:
        (list[Candidate])
    """
    url = '{index_url}/{project_name}/'.format(index_url=index_url, project_name=project_name)
    logging.getLogger('qer.net.pypi').info('Fetching versions for %s', project_name)
    contents = requests.get(url)

    class LinksHTMLParser(HTMLParser):
        def __init__(self):
            HTMLParser.__init__(self)
            self.dists = []
            self.active_link = None

        def handle_starttag(self, tag, attrs):
            if tag == 'a':
                for attr in attrs:
                    if attr[0] == 'href':
                        self.active_link = attr[1]
                        break

        def handle_data(self, data):
            if 'whl' in data:
                data_parts = data.split('-')
                name = data_parts[0]
                version = pkg_resources.parse_version(data_parts[1])
                self.dists.insert(0, Candidate(name, data, version, tuple(data_parts[2].split('.')), self.active_link))
            elif 'tar.gz' in data or 'tgz' in data:
                data_parts = data.split('-')
                name = data_parts[0]
                version = pkg_resources.parse_version(data_parts[1])
                self.dists.insert(0, Candidate(name, data, version, (), self.active_link))

    parser = LinksHTMLParser()
    parser.feed(contents.content)

    return parser.dists


def _do_download(filename, link):
    split_link = link.split('#sha256=')
    sha = split_link[1]

    if os.path.exists(filename):
        hasher = sha256()
        with open(filename, 'rb') as handle:
            while True:
                block = handle.read(1024)
                if not block:
                    break
                hasher.update(block)
        if hasher.hexdigest() == sha:
            logger.info('Reusing %s', filename)
            return filename

        print "File hash doesn't match"

    logger.info('Downloading %s -> %s', split_link[0], filename)
    response = requests.get(split_link[0], stream=True)

    with open(filename, 'wb') as handle:
        for block in response.iter_content(1024):
            handle.write(block)
    return filename


class NoCandidateException(Exception):
    def __init__(self, *args, **kwargs):
        super(NoCandidateException, self).__init__(*args, **kwargs)
        self.project_name = None
        self.specifier = None

    def __str__(self):
        return 'NoCandidateException - no candidate for "{}" satisfies {}'.format(
            self.project_name,
            self.specifier
        )


def download_candidate(project_name, py_ver='py2', specifier=None, allow_prerelease=False, skip_source=True):
    candidates = _scan_page_links('https://pypi.org/simple', project_name)

    for candidate in candidates:
        if not ('py2' in candidate.py_version or 'cp27' in candidate.py_version) and skip_source:
            continue

        if not allow_prerelease and candidate.version.is_prerelease:
            continue

        if specifier is not None and not specifier.contains(candidate.version):
            continue

        return _do_download(candidate.filename, candidate.link)

    if not skip_source:
        ex = NoCandidateException()
        ex.project_name = project_name
        ex.specifier = specifier
        raise ex

    return download_candidate(project_name, py_ver, specifier, allow_prerelease, False)


# if __name__ == '__main__':
#     download_candidate('pylint')
