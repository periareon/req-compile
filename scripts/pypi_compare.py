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
}


START_WITH = 'adzuki'

# Python 2.7
# Kinda bad:
# 2keys
# abeona  .... failed but weirdly
# abstraction, reverse dep with none extra
# adapter, ValueError: Failed to parse requires expression "~=3.6" for requirement
# zope, documenttemplate betas are not always selected correctly
# adzuki specified < prerelease condition, this caused req-compile to take a prerelease


class LinksHTMLParser(html_parser.HTMLParser):
    def __init__(self, url):
        html_parser.HTMLParser.__init__(self)
        self.url = url
        self.active_link = None
        self.active_skip = False
        self.started = False

    def handle_starttag(self, tag, attrs):
        self.active_link = None
        if tag == 'a':
            for attr in attrs:
                if attr[0] == 'href':
                    url_part = attr[1]
                    project_name = url_part.split('/')[-2]
                    self.active_link = self.url, attr[1]
                    print('Handle lib {}'.format(project_name))
                    if not self.started:
                        if project_name == START_WITH:
                            self.started = True
                        else:
                            continue

                    if project_name in WHITELIST:
                        print('Whitelisted, not running')
                    else:
                        fd, name = tempfile.mkstemp()
                        os.write(fd, (project_name + '\n').encode('utf-8'))
                        os.close(fd)

                        subprocess.check_call([sys.executable, 'compare_with_pip_compile.py', name])

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
