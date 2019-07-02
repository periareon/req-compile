from __future__ import print_function

import abc
import logging
import struct
import enum
import platform
import re
import sys

import pkg_resources
import six

import qer.metadata
import qer.utils

INTERPRETER_TAGS = {
    'CPython': 'cp',
    'IronPython': 'ip',
    'PyPy': 'pp',
    'Jython': 'jy',
}


def _get_platform_tags():
    is_32 = struct.calcsize("P") == 4
    if sys.platform == 'win32':
        if is_32:
            tag = ('win32',)
        else:
            tag = ('win_amd64',)
    elif sys.platform.startswith('linux'):
        if is_32:
            tag = ('manylinux1_' + platform.machine(), 'linux_' + platform.machine())
        else:
            tag = ('manylinux1_x86_64', 'linux_x86_64')
    else:
        raise ValueError('Unsupported platform: {}'.format(sys.platform))
    return tag


INTERPRETER_TAG = INTERPRETER_TAGS.get(platform.python_implementation(), 'cp')
PY_VERSION_NUM = str(sys.version_info.major) + str(sys.version_info.minor)

PLATFORM_TAGS = _get_platform_tags()
EXTENSIONS = ('.whl', '.tar.gz', '.tgz', '.zip')


class DistributionType(enum.Enum):
    SOURCE = 2
    WHEEL = 1
    SDIST = 0


class RequiresPython(object):
    OPS = {
        '<': lambda x, y: x < y,
        '>': lambda x, y: x > y,
        '==': lambda x, y: x == y,
        '!=': lambda x, y: x != y,
        '>=': lambda x, y: x >= y,
        '<=': lambda x, y: x <= y
    }
    SYS_PY_VERSION = pkg_resources.parse_version(sys.version.split(' ')[0])
    SYS_PY_MAJOR = pkg_resources.parse_version('{}'.format(sys.version_info.major))
    SYS_PY_MAJOR_MINOR = pkg_resources.parse_version('{}.{}'.format(sys.version_info.major,
                                                                    sys.version_info.minor))
    WHEEL_VERSION_TAGS = ('py2' if six.PY2 else 'py3',
                          INTERPRETER_TAG + PY_VERSION_NUM,
                          'py' + PY_VERSION_NUM)

    def __init__(self, py_version):
        self.py_version = py_version

    def check_compatibility(self):
        if self.py_version is None or self.py_version == ():
            return True
        if isinstance(self.py_version, tuple):
            return any(version in RequiresPython.WHEEL_VERSION_TAGS
                       for version in self.py_version)

        return all(self._check_py_constraint(part) for part in self.py_version.split(','))

    @classmethod
    def _check_py_constraint(cls, version_constraint):
        ref_version = cls.SYS_PY_VERSION
        version_part = re.split('[!=<>~]', version_constraint)[-1].strip()
        operator = version_constraint.replace(version_part, '').strip()
        if version_part.endswith('.*'):
            version_part = version_part.replace('.*', '')
            dotted_parts = len(version_part.split('.'))
            if dotted_parts == 2:
                ref_version = cls.SYS_PY_MAJOR_MINOR
            if dotted_parts == 1:
                ref_version = cls.SYS_PY_MAJOR
        version = pkg_resources.parse_version(version_part)
        return cls.OPS[operator](ref_version, version)

    @property
    def tag_score(self):
        result = 100
        version_val = None
        if not isinstance(self.py_version, tuple):
            version_val = self.py_version
        elif len(self.py_version) == 1:
            version_val = self.py_version[0]

        if version_val is not None:
            for tag_type in tuple(INTERPRETER_TAGS.values()) + ('py',):
                version_val = version_val.replace(tag_type, '')
            try:
                result += int(version_val)
            except ValueError:
                pass

        return result

    def __eq__(self, other):
        return self.py_version == other.py_version

    def __str__(self):
        if self.py_version is None or self.py_version == ():
            return 'any'

        if isinstance(self.py_version, tuple):
            return ','.join(sorted(self.py_version))
        return ''


class Candidate(object):  # pylint: disable=too-many-instance-attributes
    def __init__(self, name, filename, version, py_version, plat, link,
                 candidate_type=DistributionType.SDIST):
        """

        Args:
            name:
            filename:
            version:
            py_version (RequiresPython): Python version
            plat (str):
            link:
            type:
        """
        self.name = name
        self.filename = filename
        self.version = version
        self.py_version = py_version   # type: RequiresPython
        self.platform = plat
        self.link = link
        self.type = candidate_type

        # Sort based on tags to make sure the most specific distributions
        # are matched first
        self.sortkey = (version, candidate_type.value, self.tag_score)

        self.preparsed = None

    def _calculate_tag_score(self):
        tag_score = self.py_version.tag_score
        if platform != 'any':
            tag_score += 1000

        return tag_score

    @property
    def tag_score(self):
        result = self.py_version.tag_score
        if platform != 'any':
            result += 1000

        return result

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
        py_version_str = str(self.py_version) + '-'
        return '{} {}-{}-{}{}'.format(
            self.type.name,
            self.name, self.version, py_version_str, self.platform)


class NoCandidateException(Exception):
    def __init__(self, req, results=None):
        super(NoCandidateException, self).__init__()
        self.req = req
        self.results = results
        self.check_level = 0

    def __str__(self):
        if self.req.specifier:
            return 'NoCandidateException - no candidate for "{}" satisfies {}'.format(
                self.req.name,
                self.req.specifier
            )
        return 'NoCandidateException - no candidates found for "{}"'.format(self.req.name)


def process_distribution(source, filename, py_version=None):
    candidate = None
    if '.whl' in filename:
        candidate = _wheel_candidate(source, filename)
    elif '.tar.gz' in filename or '.tgz' in filename or '.zip' in filename:
        candidate = _tar_gz_candidate(source, filename, py_version=py_version)
    return candidate


def _wheel_candidate(source, filename):
    data_parts = filename.split('-')
    name = data_parts[0]
    version = pkg_resources.parse_version(data_parts[1])
    plat = data_parts[4].split('.')[0]
    return Candidate(name,
                     filename,
                     version,
                     RequiresPython(tuple(data_parts[2].split('.'))),
                     plat,
                     source,
                     candidate_type=DistributionType.WHEEL)


def _tar_gz_candidate(source, filename, py_version=None):
    name, version = qer.metadata.parse_source_filename(filename)
    return Candidate(name, filename, version, RequiresPython(py_version), 'any',
                     source, candidate_type=DistributionType.SDIST)


def _check_platform_compatibility(py_platform):
    return py_platform == 'any' or (py_platform.lower() in PLATFORM_TAGS)


class BaseRepository(six.with_metaclass(abc.ABCMeta, object)):
    @abc.abstractmethod
    def get_candidate(self, req):
        """Fetch the best matching candidate for the given requirement

        Args:
            req (pkg_resources.Requirement): Requirement to find a match for

        Returns:
            (Candidate) The best matching candidate
        """
        raise NotImplementedError()


class CantUseReason(enum.Enum):
    U_CAN_USE = 0
    WRONG_PYTHON_VERSION = 2
    WRONG_PLATFORM = 3
    IS_PRERELEASE = 4
    VERSION_NO_SATISFY = 5


def sort_candidates(candidates):
    """

    Args:
        candidates:

    Returns:
        (list[Candidate])
    """
    return sorted(candidates, key=lambda x: x.sortkey, reverse=True)


class Repository(six.with_metaclass(abc.ABCMeta, BaseRepository)):
    def __init__(self, logger_name, allow_prerelease=None):
        super(Repository, self).__init__()
        if allow_prerelease is None:
            allow_prerelease = False
        self.logger = logging.getLogger('qer.repository').getChild(logger_name)
        self.allow_prerelease = allow_prerelease

    def __eq__(self, other):
        return self.allow_prerelease == other.allow_prerelease

    def __iter__(self):
        return iter([self])

    @abc.abstractmethod
    def get_candidates(self, req):
        """
        Fetch all available candidates for a project_name
        Args:
            req (Requirement): Requirement to get candidates for

        Returns:
            (list[Candidate]) List of candidates
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def resolve_candidate(self, candidate):
        raise NotImplementedError()

    @abc.abstractmethod
    def close(self):
        raise NotImplementedError()

    def get_candidate(self, req):
        candidates = self.get_candidates(req)
        return self.do_get_candidate(req, candidates)

    def do_get_candidate(self, req, candidates):
        self.logger.info('Getting candidate for %s', req)
        candidates = sort_candidates(candidates)
        has_equality = qer.utils.is_pinned_requirement(req)

        check_level = 1
        for candidate in candidates:
            check_level += 1
            if not candidate.py_version.check_compatibility():
                continue

            check_level += 1
            if not _check_platform_compatibility(candidate.platform):
                continue

            check_level += 1
            if not has_equality and not self.allow_prerelease and candidate.version.is_prerelease:
                continue

            check_level += 1
            if not req.specifier.contains(candidate.version,
                                          prereleases=has_equality or self.allow_prerelease):
                continue

            check_level += 1
            if candidate.type == DistributionType.SDIST:
                self.logger.warning('Considering source distribution for %s', candidate.name)
            return self.resolve_candidate(candidate)

        ex = NoCandidateException(req)
        ex.check_level = check_level
        raise ex

    def why_cant_I_use(self, req, candidate):  # pylint: disable=invalid-name
        try:
            self.do_get_candidate(req, (candidate,))
            raise ValueError('This requirement can be used')
        except NoCandidateException as ex:
            return CantUseReason(ex.check_level)
