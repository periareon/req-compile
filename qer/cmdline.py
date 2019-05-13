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
    if reason == CantUseReason.WRONG_PLATFORM:
        return 'platform mismatch {}'.format(qer.repos.repository.PLATFORM_TAG)
    if reason == CantUseReason.WRONG_PYTHON_VERSION:
        return 'python version/interpreter mismatch ({})'.format(', '.join(
            qer.repos.repository.RequiresPython.WHEEL_VERSION_TAGS))
    if reason == CantUseReason.IS_PRERELEASE:
        return 'prereleases not used'

    return 'unknown'


def _repo_as_list(repo):
    if isinstance(repo, MultiRepository):
        return repo.repositories
    return [repo]


def _generate_no_candidate_display(req, repo, dists):
    repos = _repo_as_list(repo)

    failing_node = dists[req.name]
    nodes = failing_node.reverse_deps
    constraints = failing_node.build_constraints()
    if not nodes:
        print('No package available for {}, latest is {}'.format(req.name, 'unknown'), file=sys.stderr)
    else:
        can_satisfy = is_possible(constraints)
        if not can_satisfy:
            print('No version could possibly satisfy the following requirements:', file=sys.stderr)
        else:
            print('No version of {} could satisfy the following requirements:'.format(req.name), file=sys.stderr)

        for node in nodes:
            print('   {} requires {}'.format(node, node.dependencies[failing_node]), file=sys.stderr)

        if can_satisfy:
            all_candidates = {repo: repo.get_candidates(req) for repo in repos}
            if sum(len(candidates) for candidates in all_candidates.values()) == 0:
                print('No candidates found in any of the input sources', file=sys.stderr)
            else:
                _dump_repo_candidates(req, repos)


def _dump_repo_candidates(req, repos):
    print('Found the following candidates, none of which will work:', file=sys.stderr)
    for repo in repos:
        candidates = repo.get_candidates(req)
        print('  {}:'.format(repo), file=sys.stderr)
        if candidates:
            for candidate in repo._sort_candidates(candidates):
                print('  {}: {}'.format(candidate,
                                        _cantusereason_to_text(repo.why_cant_I_use(req, candidate))),
                      file=sys.stderr)
        else:
            print('  No candidates found', file=sys.stderr)


def _create_input_reqs(input_arg, extra_source_repos):
    if os.path.isdir(input_arg):
        dist = qer.metadata.extract_metadata(input_arg)
        if dist is None:
            raise ValueError('Input arg "{}" is not directory containing setup.py or requirements file'.format(input_arg))
        # source_repo = SourceRepository(input_arg)
        extra_source_repos.append(input_arg)
        return [utils.parse_requirement(dist.name)]
    else:
        return utils.reqs_from_files([input_arg])


def run_compile(input_args, constraint_files, sources, find_links, index_url, wheeldir, no_index, remove_source,
                solution):

    if wheeldir:
        if not os.path.exists(wheeldir):
            os.mkdir(wheeldir)
        delete_wheeldir = False
    else:
        wheeldir = tempfile.mkdtemp()
        delete_wheeldir = True

    extra_sources = []
    input_reqs = {
        input_arg: _create_input_reqs(input_arg, extra_sources)
        for input_arg in input_args
    }
    if extra_sources:
        remove_source = True

    sources = extra_sources + sources

    if constraint_files:
        constraint_reqs = utils.reqs_from_files(constraint_files)
    else:
        constraint_reqs = None

    repo = build_repo(solution, sources, find_links, index_url, no_index, wheeldir)

    try:
        results, roots, constraints = perform_compile(input_reqs, repo, constraint_reqs=constraint_reqs)

        req_filter = None

        if remove_source:
            if not any(isinstance(r, SourceRepository) for r in _repo_as_list(repo)):
                raise ValueError('Cannot remove results from source, no source provided')

            def is_from_source(dist):
                return not hasattr(dist.metadata, 'origin') or not isinstance(dist.metadata.origin, SourceRepository)

            req_filter = is_from_source

        lines = sorted(results.generate_lines(roots, req_filter=req_filter), key=lambda x: x[0].lower())
        left_column_len = max(len(x[0]) for x in lines)
        for line in lines:
            print('{}  # {}'.format(line[0].ljust(left_column_len), line[1]))
    except qer.repos.repository.NoCandidateException as ex:
        _generate_no_candidate_display(ex.req, repo, ex.results)
        sys.exit(1)
    finally:
        if delete_wheeldir:
            shutil.rmtree(wheeldir)


def build_repo(solution, sources, find_links, index_url, no_index, wheeldir):
    repos = []
    if solution:
        repos.append(SolutionRepository(solution))
    if sources:
        repos.extend(SourceRepository(source) for source in sources)
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


class IndentFilter(logging.Filter):
    def filter(self, record):
        depth = getattr(record, 'depth', 0)
        record.msg = (' ' * depth) + record.msg
        return record


def compile_main():
    logging.basicConfig(level=logging.ERROR)

    parser = argparse.ArgumentParser()
    parser.add_argument('requirement_files', nargs='+', help='Input requirements files')
    parser.add_argument('-v', '--verbose', default=False, action='store_true',
                        help='Enable verbose output to stderr')
    parser.add_argument('-c', '--constraints', action='append',
                        help='Contraints files. Not included in final compilation')
    parser.add_argument('--remove-source', default=False, action='store_true',
                        help='Remove distributions satisfied via --source from the output')
    parser.add_argument('-u', '--solution', type=str, default=None,
                        help='Existing fully-pinned constraints file to use as a baseline when compiling')

    add_repo_args(parser)

    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)
        logging.getLogger('qer').setLevel(logging.DEBUG)

        logging.getLogger('qer.compile').addFilter(IndentFilter())

    run_compile(args.requirement_files, args.constraints if args.constraints else None, args.sources, args.find_links,
                args.index_url, args.wheel_dir, args.no_index, args.remove_source, args.solution)


def add_repo_args(parser):
    parser.add_argument('-i', '--index-url', type=str, default=None)
    parser.add_argument('-f', '--find-links', type=str, default=None)
    parser.add_argument('-s', '--source', nargs='+', dest='sources', default=[])
    parser.add_argument('-w', '--wheel-dir', type=str, default=None)
    parser.add_argument('--no-index',
                        action='store_true', default=False,
                        help='Do not connect to the internet to compile. All wheels must be '
                             'available in --find-links paths.')


if __name__ == '__main__':
    compile_main()
