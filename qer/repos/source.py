from __future__ import print_function
import collections
import itertools
import os
import sys

from qer import utils
import qer.metadata
import qer.repos.repository

from qer.repos.repository import Repository

SPECIAL_DIRS = ('site-packages', 'dist-packages', '.git', '.svn', '.idea')
SPECIAL_FILES = ('__init__.py',)


class SourceRepository(Repository):
    def __init__(self, path):
        super(SourceRepository, self).__init__('source', allow_prerelease=True)

        if not os.path.exists(path):
            raise ValueError('Source directory {} does not exist (cwd={})'.format(path, os.getcwd()))

        self.path = os.path.abspath(path)
        self.distributions = collections.defaultdict(list)
        self._find_all_distributions()

    def _find_all_distributions(self):
        for root, dirs, files in os.walk(self.path):
            for dir_ in dirs:
                if dir_ in SPECIAL_DIRS:
                    dirs.remove(dir_)

            for filename in files:
                if filename in SPECIAL_FILES:
                    for dir_ in dirs:
                        dirs.remove(dir_)
                elif filename == 'setup.py':
                    for dir_ in list(dirs):
                        dirs.remove(dir_)

                    try:
                        result = qer.metadata.extract_metadata(root, origin=self)
                        candidate = qer.repos.repository.Candidate(
                            result.name,
                            root,
                            result.version,
                            qer.repos.repository.RequiresPython(None),
                            'any',
                            None,
                            qer.repos.repository.DistributionType.SOURCE)
                        candidate.preparsed = result
                        self.distributions[utils.normalize_project_name(result.name)].append(candidate)
                    except qer.metadata.MetadataError as ex:
                        print('Failed to parse metadata for {} - {}'.format(root, str(ex)),
                              file=sys.stderr)
                    break

    def __repr__(self):
        return '--source {}'.format(self.path)

    def __eq__(self, other):
        return (isinstance(other, SourceRepository) and
                super(SourceRepository, self).__eq__(other) and
                self.path == other.path)

    def __hash__(self):
        return hash('source') ^ hash(self.path)

    def get_candidates(self, req):
        if req is None:
            return itertools.chain(*self.distributions.values())

        project_name = utils.normalize_project_name(req.name)
        return self.distributions.get(project_name, [])

    def resolve_candidate(self, candidate):
        return candidate.preparsed, True

    def close(self):
        pass
