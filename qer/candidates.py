from __future__ import print_function
import argparse
import shutil
import tempfile

import pkg_resources

from qer.cmdline import add_repo_args, build_repo


def candidates_main():
    parser = argparse.ArgumentParser()
    parser.add_argument('project_name', help='Print candidates found for the project')
    add_repo_args(parser)

    args = parser.parse_args()

    wheeldir = tempfile.mkdtemp()
    repo = build_repo(None, args.source, None, args.find_links, args.index_url,
                      args.no_index, wheeldir)

    try:
        candidates = repo.get_candidates(pkg_resources.Requirement.parse(args.project_name))
        for candidate in candidates:
            print(candidate)
    finally:
        shutil.rmtree(wheeldir)


if __name__ == '__main__':
    candidates_main()
