import pkg_resources

import qer.pypi
from qer.repository import Candidate, DistributionType, RequiresPython


def test_links_parser_wheel():
    filename = 'pytest-4.3.0-py2.py3-none-any.whl'
    url = 'https://url'
    lp = qer.pypi.LinksHTMLParser(url)
    lp.active_link = url, filename
    lp.handle_data(filename)
    assert lp.dists == [Candidate('pytest', filename, pkg_resources.parse_version('4.3.0'),
                                  RequiresPython(('py2', 'py3')), 'any', (url, filename), DistributionType.WHEEL)]


def test_links_py3_wheel():
    filename = 'PyVISA-1.9.1-py3-none-any.whl'
    url = 'https://url'
    lp = qer.pypi.LinksHTMLParser(url)
    lp.active_link = url, filename
    lp.handle_data(filename)
    assert lp.dists == [Candidate('PyVISA', filename, pkg_resources.parse_version('1.9.1'), RequiresPython(('py3',)), 'any', (url, filename), DistributionType.WHEEL)]


def test_links_parser_tar_gz_hyph():
    filename = 'PyVISA-py-0.3.1.tar.gz'
    url = 'https://url'
    lp = qer.pypi.LinksHTMLParser(url)
    lp.active_link = url, filename
    lp.handle_data(filename)
    assert lp.dists == [Candidate('PyVISA_py', filename, pkg_resources.parse_version('0.3.1'), RequiresPython(None), 'any', (url, filename), DistributionType.SDIST)]


def test_tar_gz_dot():
    filename = 'backports.html-1.1.0.tar.gz'
    candidate = qer.repository._tar_gz_candidate('test', filename)

    assert candidate == \
        Candidate('backports.html', filename, pkg_resources.parse_version('1.1.0'), RequiresPython(None), 'any', 'test', DistributionType.SDIST)


def test_wheel_dot():
    filename = 'backports.html-1.1.0-py2.py3-none-any.whl'
    candidate = qer.repository._wheel_candidate('test', filename)

    assert candidate == \
        Candidate('backports.html', filename,
                           pkg_resources.parse_version('1.1.0'), RequiresPython(('py2', 'py3')), 'any', 'test', DistributionType.WHEEL)


def test_wheel_platform_specific_tags():
    filename = 'pywin32-224-cp27-cp27m-win_amd64.whl'
    candidate = qer.repository._wheel_candidate('test', filename)

    assert candidate == \
        Candidate('pywin32', filename,
                           pkg_resources.parse_version('224'), RequiresPython(('cp27',)), 'win_amd64', 'test', DistributionType.WHEEL)
