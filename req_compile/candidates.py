"""Dump candidates for requirements from repositories"""
# pylint: disable=too-many-branches

from __future__ import print_function

import argparse
import logging
import shutil
import sys
import tempfile
import time

import pkg_resources

from req_compile.cmdline import add_logging_args, add_repo_args, build_repo
from req_compile.repos.pypi import PyPIRepository
from req_compile.repos.repository import filter_candidates, sort_candidates
from req_compile.repos.source import SourceRepository


def candidates_main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_argument_group("Candidate")
    group.add_argument(
        "project_name",
        nargs="?",
        type=str,
        default=None,
        help="Print candidates found for the project. If not provided, "
        "will print all candidates for any project in the repository",
    )
    group.add_argument(
        "--all",
        default=False,
        action="store_true",
        help="Show all, including incompatible, candidates",
    )
    group.add_argument(
        "-p",
        "--pre",
        dest="allow_prerelease",
        default=False,
        action="store_true",
        help="Allow prereleases from all sources",
    )
    group.add_argument(
        "--paths",
        default=False,
        action="store_true",
        help="Print projects as a path,name tuple",
    )
    group.add_argument(
        "--paths-only",
        default=False,
        action="store_true",
        help="Print projects as paths",
    )
    add_logging_args(parser)
    add_repo_args(parser)
    args = parser.parse_args()

    logger = logging.getLogger("req_compile")
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)
        logger.setLevel(logging.DEBUG)
    else:
        logging.basicConfig(level=logging.CRITICAL, stream=sys.stderr)

    start = time.time()
    wheeldir = tempfile.mkdtemp(suffix="-wheeldir")
    repo = build_repo(
        [],
        [],
        args.sources,
        args.excluded_sources,
        args.find_links,
        args.index_urls,
        args.no_index,
        wheeldir,
        allow_prerelease=args.allow_prerelease,
    )

    if isinstance(repo, PyPIRepository) and args.project_name is None:
        repo = SourceRepository(".")

    total_candidates = 0
    try:
        req = None
        if args.project_name:
            req = pkg_resources.Requirement.parse(args.project_name)

        candidates = repo.get_candidates(req)
        if not args.all:
            candidates = filter_candidates(
                req, candidates, allow_prereleases=args.allow_prerelease
            )

        for candidate in sort_candidates(candidates):
            if args.paths or args.paths_only:
                print(candidate.filename, end="")
                if not args.paths_only:
                    print(",", end="")
                    print(candidate.name)
                else:
                    print("")
            else:
                print(candidate)
            total_candidates += 1
    finally:
        shutil.rmtree(wheeldir)
        end = time.time()
        print(
            "Found %d%s candidate(s) in %0.2f seconds"
            % (total_candidates, " compatible" if not args.all else "", (end - start)),
            file=sys.stderr,
        )


if __name__ == "__main__":
    candidates_main()
