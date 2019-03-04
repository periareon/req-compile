import abc
import collections
import platform
import sys

import six

INTERPRETER_TAGS = {
    'CPython': 'cp',
    'IronPython': 'ip',
    'PyPy': 'pp',
    'Jython': 'jy',
}
INTERPRETER_TAG = INTERPRETER_TAGS.get(platform.python_implementation(), 'cp')

PY_VERSION_NUM = str(sys.version_info.major) + str(sys.version_info.minor)


Candidate = collections.namedtuple('Candidate', 'name filename version py_version platform link')


class NoCandidateException(Exception):
    def __init__(self, *args):
        super(NoCandidateException, self).__init__(*args)
        self.req = None
        self.results = None
        self.constraint_results = None
        self.mapping = None

    def __str__(self):
        return 'NoCandidateException - no candidate for "{}" satisfies {}'.format(
            self.req.name,
            self.req.specifier
        )

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


class BaseRepository(six.with_metaclass(abc.ABCMeta, object)):
    @abc.abstractmethod
    def get_candidate(self, req):
        raise NotImplementedError()

    def source_of(self, req):
        return self


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
        return self._do_get_candidate(req)

    def _do_get_candidate(self, req, skip_source=True):
        self.logger.info('Getting candidate for %s', req)
        candidates = self.get_candidates(req)
        has_equality = any(spec.operator == '==' for spec in req.specifier)

        for candidate in candidates:
            if skip_source and not candidate.filename.endswith('.whl'):
                continue

            if not _check_py_compatibility(candidate.py_version):
                continue

            if not _check_platform_compatibility(candidate.platform):
                continue

            if not has_equality and not self.allow_prerelease and candidate.version.is_prerelease:
                continue

            if not req.specifier.contains(candidate.version):
                continue

            return self.resolve_candidate(candidate)

        if not skip_source:
            ex = NoCandidateException()
            ex.req = req
            raise ex

        return self._do_get_candidate(req, skip_source=False)


class MultiRepository(BaseRepository):
    def __init__(self, *repositories):
        super(MultiRepository, self).__init__()
        self.repositories = list(repositories)  # type: list[Repository]
        self.source = {}

    def get_candidate(self, req):
        for repo in self.repositories:
            try:
                result = repo.get_candidate(req)
                self.source[req.name] = repo
                return result
            except NoCandidateException:
                pass

    def source_of(self, req):
        return self.source[req.name]
