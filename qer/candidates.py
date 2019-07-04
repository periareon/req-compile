from __future__ import print_function
import argparse
import shutil
import tempfile

import pkg_resources

from qer.cmdline import add_repo_args, build_repo
from qer.repos.pypi import PyPIRepository
from qer.repos.source import SourceRepository


def candidates_main():
    parser = argparse.ArgumentParser()
    group = parser.add_argument_group('Candidate')
    group.add_argument('project_name', nargs='?', type=str, default=None,
                       help='Print candidates found for the project. If not provided, '
                            'will print all candidates for any project in the repository')
    group.add_argument('--paths', default=False, action='store_true',
                       help='Print projects as a path,name tuple')
    group.add_argument('--paths-only', default=False, action='store_true',
                       help="Print projects as paths")
    add_repo_args(parser)

    args = parser.parse_args()

    wheeldir = tempfile.mkdtemp()
    repo = build_repo(None, None, args.sources, args.find_links, args.index_urls, args.no_index, wheeldir)

    if isinstance(repo, PyPIRepository) and args.project_name is None:
        repo = SourceRepository('.')

    try:
        req = None
        if args.project_name:
            req = pkg_resources.Requirement.parse(args.project_name)
        candidates = repo.get_candidates(req)
        for candidate in candidates:
            if args.paths or args.paths_only:
                print(candidate.filename, end='')
                if not args.paths_only:
                    print(',', end='')
                    print(candidate.name)
                else:
                    print('')
            else:
                print(candidate)
    finally:
        shutil.rmtree(wheeldir)


if __name__ == '__main__':
    candidates_main()
