from __future__ import print_function

import argparse
import logging
import os
import shutil
import sys
import tempfile

import qer.compile
import qer.dists
import qer.metadata
import qer.repos.pypi

from qer import utils
from qer.compile import perform_compile
from qer.repos.findlinks import FindLinksRepository
from qer.repos.pypi import PyPIRepository
from qer.repos.repository import CantUseReason
from qer.repos.multi import MultiRepository
from qer.repos.solution import SolutionRepository
from qer.repos.source import SourceRepository
from qer.versions import is_possible


def _cantusereason_to_text(reason):
    if reason == CantUseReason.VERSION_NO_SATISFY:
        return 'version mismatch'
    elif reason == CantUseReason.WRONG_PLATFORM:
        return 'platform mismatch {}'.format(qer.repos.repository.PLATFORM_TAG)
    elif reason == CantUseReason.WRONG_PYTHON_VERSION:
        return 'python version/interpreter mismatch ({})'.format(', '.join(
            qer.repos.repository.RequiresPython.WHEEL_VERSION_TAGS))
    elif reason == CantUseReason.IS_PRERELEASE:
        return 'prereleases not used'

    return 'unknown'


def _generate_no_candidate_display(ex, repo, dists):
    if isinstance(repo, MultiRepository):
        repos = repo.repositories
    else:
        repos = [repo]

    failing_node = dists[ex.req.name]
    nodes = failing_node.reverse_deps
    constraints = failing_node.build_constraints()
    if not nodes:
        print('No package available for {}, latest is {}'.format(ex.req.name, 'unknown'), file=sys.stderr)
    else:
        can_satisfy = is_possible(constraints)
        if not can_satisfy:
            print('No version could possibly satisfy the following requirements:', file=sys.stderr)
        else:
            print('No version of {} could satisfy the following requirements:'.format(ex.req.name), file=sys.stderr)

        for node in nodes:
            print('   {} requires {}'.format(node, node.dependencies[failing_node]), file=sys.stderr)

        if can_satisfy:
            all_candidates = {repo: repo.get_candidates(ex.req) for repo in repos}
            if sum(len(candidates) for candidates in all_candidates.values()) == 0:
                print('No candidates found in any of the input sources', file=sys.stderr)
            else:
                print('Found the following candidates, none of which will work:', file=sys.stderr)
                for repo in repos:
                    candidates = repo.get_candidates(ex.req)
                    print('  {}:'.format(repo), file=sys.stderr)
                    if candidates:
                        for candidate in repo._sort_candidates(candidates):
                            print('  {}: {}'.format(candidate,
                                                    _cantusereason_to_text(repo.why_cant_I_use(ex.req, candidate))),
                                  file=sys.stderr)
                    else:
                        print('  No candidates found', file=sys.stderr)


def run_compile(input_reqfiles, constraint_files, source, force_extras, find_links,
                index_url, wheeldir, no_index, remove_source, solution):

    if wheeldir:
        if not os.path.exists(wheeldir):
            os.mkdir(wheeldir)
        delete_wheeldir = False
    else:
        wheeldir = tempfile.mkdtemp()
        delete_wheeldir = True

    if len(input_reqfiles) == 1 and os.path.isdir(input_reqfiles[0]):
        dist = qer.metadata.extract_metadata(input_reqfiles[0])
        input_reqs = [utils.parse_requirement(dist.name)]
    else:
        input_reqs = {
            req_file: utils.reqs_from_files([req_file])
            for req_file in input_reqfiles
        }

    if constraint_files:
        constraint_reqs = utils.reqs_from_files(constraint_files)
    else:
        constraint_reqs = None

    repo = build_repo(solution, source, force_extras, find_links, index_url, no_index, wheeldir)

    try:
        results = perform_compile(input_reqs, repo, constraint_reqs=constraint_reqs)

        filter = None

        if remove_source:
            source_repo = None
            for repo in repo.repositories:
                if isinstance(repo, SourceRepository):
                    source_repo = repo

            if source_repo is None:
                raise ValueError('Cannot remove results from source, no source provided')

            filter = lambda dist: not hasattr(dist.metadata, 'origin') or dist.metadata.origin is not source_repo

        lines = sorted(results.generate_lines(filter=filter), key=str.lower)
        print('\n'.join(lines))
    except qer.repos.repository.NoCandidateException as ex:
        _generate_no_candidate_display(ex, repo, ex.results)
        sys.exit(1)

    if delete_wheeldir:
        shutil.rmtree(wheeldir)


def build_repo(solution, source, force_extras, find_links, index_url, no_index, wheeldir):
    repos = []
    if solution:
        repos.append(SolutionRepository(solution))
    if source:
        repos.append(SourceRepository(source, force_extras=force_extras))
    if find_links:
        repos.append(FindLinksRepository(find_links))
    if not no_index:
        index_url = index_url or 'https://pypi.org/simple'
        repos.append(PyPIRepository(index_url, wheeldir))
    if not repos:
        raise ValueError('At least one Python distributions source must be provided.')
    if len(repos) > 1:
        repo = MultiRepository(*repos)
    else:
        repo = repos[0]
    return repo


def compile_main():
    logging.basicConfig(level=logging.ERROR)

    parser = argparse.ArgumentParser()
    parser.add_argument('requirement_files', nargs='+', help='Input requirements files')
    parser.add_argument('-c', '--constraints', action='append',
                        help='Contraints files. Not included in final compilation')
    parser.add_argument('--remove-source', default=False, action='store_true',
                        help='Remove distributions satisfied via --source from the output')
    parser.add_argument('-e', '--extra', nargs='+', default=[],
                        help='Extras to include for every discovered distribution '
                             'provided via --source')
    parser.add_argument('-u', '--solution', type=str, default=None,
                        help='Existing fully-pinned constraints file to use as a baseline when compiling')

    add_repo_args(parser)

    args = parser.parse_args()
    run_compile(args.requirement_files, args.constraints if args.constraints else None, args.source, tuple(args.extra), args.find_links, args.index_url,
                args.wheel_dir, args.no_index, args.remove_source, args.solution)


def add_repo_args(parser):
    parser.add_argument('-i', '--index-url', type=str, default=None)
    parser.add_argument('-f', '--find-links', type=str, default=None)
    parser.add_argument('-s', '--source', type=str, default=None)
    parser.add_argument('-w', '--wheel-dir', type=str, default=None)
    parser.add_argument('--no-index',
                        action='store_true', default=False,
                        help='Do not connect to the internet to compile. All wheels must be '
                             'available in --find-links paths.')


if __name__ == '__main__':
    compile_main()
