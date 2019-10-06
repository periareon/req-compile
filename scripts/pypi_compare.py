import argparse
import os
import subprocess
import sys
import tempfile

from six.moves import html_parser


WHITELIST = {
    '090807040506030201testpip',
    '99d4aa80-d846-424f-873b-a02c7215fc54',
    'abseqpy',  # pip-compile is wrong
    'accepts',  # extraordinarily broken tar file
    'acrylamid',  # Adds an install_req at runtime that's not in the dist info
    'adversarial-robustness-toolbox',  # agree to disagree, weird project
    'aegeantools',  # declares its versions wrong
    'ageliaco-rd',  # DocumentTemplate.  I think pip-tools is wrong about this
    'ageliaco-rd2',  # DocumentTemplate.  I think pip-tools is wrong about this
    'flask-apiform',  # wrong metadata in the package
    'flask-async',  # Source version is different from metadata
    'flaskbb-plugin-conversations',  # unsupported circular dep
    'pytestmetadata',
    'pytest-molecule',  # req-compile chooses the right non-prerelease version
    'pytest-reana',  # same
    'pytest-zafira',  # pip-compile is WRONG.  1.0.3 is not compatible with py2
    'pytgbot',  # pip-compile apparently didn't notice requests[security]
    'python-active-directory',  # relies on pyldap to be installed.  It's not?
    'python-afl', 'python-afl-ph4',  # questionable cython practice
    'python-axolotl',  # non-prerelease
    'python-bean',  # pip-compile did not deal with incomplete dist correctly. missing requirements.txt
    'python-ping',  # several of the version numbers look like prereleases.  Not sure how pip-compile handles this
    'python-slimta',  # non-prerelease
    'python-spresso',  # requests[socks]
    'mb-confy',  # totally broken package. req-compile seems slightly righter
    'mdfreader',  # messes with requirements based on cython succeeding, but not toml
    'pyhgnc',  # uses flasgger which pip-compile gets wrong. Duplicate req entries
    'flasgger',  # refers to jsonschema twice
    'pyhrf',  # Package is pretty bad and depends on an older version of pip. req-compile gets it kinda right
    'pynfdump',  # Very old, hard to parse package. Works if you pass --pre
    'pyobjc',
    'dataf',  # req-compile gets it right due to flasgger
    'datagovsg-api',  # says its verison is post0, but wheel disagrees
    'dataone-test-utilities',  # Pretty sure pip has trouble with the filter() it uses on requirements
    'multi-mechanize',  # the root req of the failure above
    'datastore-viewer',  # flasgger related failure
    'dataultra-commandlines',  # pip disagrees with req-compile on whether or not this prerelease should be used
    'deepspeech',  # pip is taking alphas here...
    'deepspeech-gpu',
    'demo-reader',  # archive is wrong
    'device-proxy',  # filter in requirements list again
    'digs',  # map in requirements list
    'diogenes8',  # disagree on whether >3.7 should allow python 3.7
}

START_WITH = 'diogenes8'


# Python 2.7
# Kinda bad:
# abeona  .... failed but weirdly
# zope, documenttemplate betas are not always selected correctly
# aegeantools 2.0.2.post1 sorted incorrectly
# pythonruntimediagnostics - seems very slow (appears to be due to bokeh)
# pymc - failed hard
# pyobjc - hung. Seems bad

# Python 3.7
# devlfunia - had a None path

# Good projects
# python-watcher - substantial number of reqs
# dexterity-localroles - huge one

class LinksHTMLParser(html_parser.HTMLParser):
    def __init__(self, url):
        html_parser.HTMLParser.__init__(self)
        self.url = url
        self.active_link = None
        self.active_skip = False
        self.started = False

        self.started_with = START_WITH
        self.total_matches = 0
        self.total_req_succeed_pip_fail = 0
        self.active_project = None

    def handle_starttag(self, tag, attrs):
        self.active_link = None
        if tag == 'a':
            for attr in attrs:
                if attr[0] == 'href':
                    url_part = attr[1]
                    project_name = url_part.split('/')[-2]
                    self.active_link = self.url, attr[1]
                    if not self.started:
                        if project_name == START_WITH:
                            self.started = True
                        else:
                            continue
                    print('Handle lib {}'.format(project_name))

                    if project_name in WHITELIST:
                        print('Whitelisted, not running')
                    else:
                        fd, name = tempfile.mkstemp()
                        os.write(fd, (project_name + '\n').encode('utf-8'))
                        os.close(fd)

                        self.active_project = project_name
                        returncode = subprocess.call([sys.executable, 'compare_with_pip_compile.py', name])
                        if returncode == 0:
                            self.total_matches += 1
                        elif returncode == 1:
                            self._dump_summary()
                        elif returncode == 2:
                            self._dump_summary()
                        elif returncode == 3:
                            self.total_req_succeed_pip_fail += 1

    def _dump_summary(self):
        print('Done:\nEnded at: {}\nTotal run: {}\nReq-compile processed but pip failed:{}\n'.format(
              self.active_project, self.total_matches, self.total_req_succeed_pip_fail))
        sys.exit(1)

    def handle_data(self, data):
        pass

    def error(self, message):
        pass


def _scan_page_links(filename):
    parser = LinksHTMLParser('http://pypi.org')
    with open(filename, 'r') as fh:
        while True:
            content = fh.read(1024)
            if not content:
                break
            parser.feed(content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('filename')

    args = parser.parse_args()
    _scan_page_links(args.filename)


if __name__ == '__main__':
    main()
