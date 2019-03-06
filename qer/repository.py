import abc
import collections
import enum
import platform
import sys

import pkg_resources
import six

INTERPRETER_TAGS = {
    'CPython': 'cp',
    'IronPython': 'ip',
    'PyPy': 'pp',
    'Jython': 'jy',
}


def _get_platform_tag():
    if sys.platform == 'win32':
        if platform.machine() == 'AMD64':
            tag = 'win_amd64'
        else:
            tag = 'win32'
    elif sys.platform.startswith('linux'):
        if platform.machine() == 'x86_64':
            tag = 'manylinux1_x86_64'
        else:
            tag = 'manylinux1_' + platform.machine()
    else:
        raise ValueError('Unsupported platform: {}'.format(sys.platform))
    return tag


INTERPRETER_TAG = INTERPRETER_TAGS.get(platform.python_implementation(), 'cp')
PY_VERSION_NUM = str(sys.version_info.major) + str(sys.version_info.minor)
IMPLEMENTATION_TAGS = ('py2' if six.PY2 else 'py3', INTERPRETER_TAG + PY_VERSION_NUM)

PLATFORM_TAG = _get_platform_tag()
EXTENSIONS = ('.whl', '.tar.gz', '.tgz', '.zip')


class DistributionType(enum.Enum):
    WHEEL = 1
    SDIST = 0


class Candidate(object):
    def __init__(self, name, filename, version, py_version, platform, link, type=DistributionType.SDIST):
        self.name = name
        self.filename = filename
        self.version = version
        self.py_version = py_version
        self.platform = platform
        self.link = link
        self.type = type

        # Sort based on tags to make sure the most specific distributions
        # are matched first
        tag_score = self._calculate_tag_score(py_version, platform)
        self.sortkey = (type.value, version, tag_score)

    @staticmethod
    def _calculate_tag_score(py_version, platform):
        tag_score = 0
        if py_version != ():
            tag_score += 100

            version_val = None
            if not isinstance(py_version, tuple):
                version_val = py_version
            elif len(py_version) == 1:
                version_val = py_version[0]

            if version_val is not None:
                for tag_type in tuple(INTERPRETER_TAGS.values()) + ('py',):
                    version_val = version_val.replace(tag_type, '')
                try:
                    tag_score += int(version_val)
                except ValueError:
                    pass

        if platform != 'any':
            tag_score += 1000

        return tag_score

    def __eq__(self, other):
        return (self.name == other.name and
                self.filename == other.filename and
                self.version == other.version and
                self.py_version == other.py_version and
                self.platform == other.platform and
                self.link == other.link and
                self.type == other.type)

    def __repr__(self):
        return 'Candidate(name={}, filename={}, version={}, py_version={}, platform={}, link={})'.format(
            self.name, self.filename, self.version, self.py_version, self.platform, self.link
        )

    def __str__(self):
        py_version_str = 'any'
        if self.py_version:
            py_version_str = ','.join(self.py_version)
        return '{} {}-{}-{}-{}'.format(
            self.type.name,
            self.name, self.version, py_version_str, self.platform)


class NoCandidateException(Exception):
    def __init__(self, *args):
        super(NoCandidateException, self).__init__(*args)
        self.req = None
        self.results = None
        self.constraint_results = None
        self.mapping = None
        self.check_level = 0

    def __str__(self):
        return 'NoCandidateException - no candidate for "{}" satisfies {}'.format(
            self.req.name,
            self.req.specifier
        )


def process_distribution(source, filename):
    candidate = None
    if '.whl' in filename:
        candidate = _wheel_candidate(source, filename)
    elif '.tar.gz' in filename or '.tgz' in filename or '.zip' in filename:
        candidate = _tar_gz_candidate(source, filename)
    return candidate


def _wheel_candidate(source, filename):
    data_parts = filename.split('-')
    name = data_parts[0]
    version = pkg_resources.parse_version(data_parts[1])
    platform = data_parts[4].split('.')[0]
    return Candidate(name,
                     filename,
                     version,
                     tuple(data_parts[2].split('.')),
                     platform,
                     source,
                     type=DistributionType.WHEEL)


def _tar_gz_candidate(source, filename):
    data_parts = filename.split('-')
    version_idx = -1
    for idx, part in enumerate(data_parts):
        if part[0].isdigit() and '.' in part:
            version_idx = idx
            break

    name = '_'.join(data_parts[:version_idx])
    version_text = data_parts[version_idx]
    for ext in EXTENSIONS:
        version_text = version_text.replace(ext, '')

    version = pkg_resources.parse_version(version_text)
    return Candidate(name, filename, version, (), 'any', source, type=DistributionType.SDIST)


def _check_py_compatibility(py_version):
    # https://www.python.org/dev/peps/pep-0425/
    return py_version == () or any(version in IMPLEMENTATION_TAGS for version in py_version)


def _check_platform_compatibility(py_platform):
    return py_platform == 'any' or py_platform.lower() == PLATFORM_TAG


class BaseRepository(six.with_metaclass(abc.ABCMeta, object)):
    @abc.abstractmethod
    def get_candidate(self, req):
        raise NotImplementedError()

    def source_of(self, req):
        return self


class CantUseReason(enum.Enum):
    U_CAN_USE = 0
    WRONG_PYTHON_VERSION = 2
    WRONG_PLATFORM = 3
    IS_PRERELEASE = 4
    VERSION_NO_SATISFY = 5


class Repository(six.with_metaclass(abc.ABCMeta, object)):
    def __init__(self, allow_prerelease=None):
        if allow_prerelease is None:
            allow_prerelease = False

        self.allow_prerelease = allow_prerelease

    @abc.abstractmethod
    def get_candidates(self, req):
        """
        Fetch all available candidates for a project_name
        Args:
            project_name (str): Project name as it appears in a requirements file

        Returns:
            (list) List of candidates
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def resolve_candidate(self, candidate):
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def logger(self):
        raise NotImplementedError()

    @abc.abstractmethod
    def close(self):
        raise NotImplementedError()

    def get_candidate(self, req):
        candidates = self.get_candidates(req)
        return self._do_get_candidate(req, candidates)

    def _do_get_candidate(self, req, candidates):
        self.logger.info('Getting candidate for %s', req)
        candidates = self._sort_candidates(candidates)
        has_equality = any(spec.operator == '==' for spec in req.specifier)

        check_level = 1
        for candidate in candidates:
            check_level += 1
            if not _check_py_compatibility(candidate.py_version):
                continue

            check_level += 1
            if not _check_platform_compatibility(candidate.platform):
                continue

            check_level += 1
            if not has_equality and not self.allow_prerelease and candidate.version.is_prerelease:
                continue

            check_level += 1
            if not req.specifier.contains(candidate.version, prereleases=has_equality):
                continue

            check_level += 1
            return self.resolve_candidate(candidate)

        ex = NoCandidateException()
        ex.req = req
        ex.check_level = check_level
        raise ex

    def why_cant_I_use(self, req, candidate):
        try:
            self._do_get_candidate(req, (candidate,))
            raise ValueError('This requirement can be used')
        except NoCandidateException as ex:
            return CantUseReason(ex.check_level)

    def _sort_candidates(self, candidates):
        return sorted(candidates, key=lambda x: x.sortkey, reverse=True)


class MultiRepository(BaseRepository):
    def __init__(self, *repositories):
        super(MultiRepository, self).__init__()
        self.repositories = list(repositories)  # type: list[Repository]
        self.source = {}

    def get_candidate(self, req):
        last_ex = None
        for repo in self.repositories:
            try:
                candidates = repo.get_candidates(req)
                result = repo._do_get_candidate(req, candidates)
                self.source[req.name] = repo
                return result
            except NoCandidateException as ex:
                last_ex = ex
        raise last_ex

    def source_of(self, req):
        return self.source[req.name]
