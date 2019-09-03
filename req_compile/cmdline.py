# coding=utf-8
from __future__ import print_function

import argparse
import datetime
import itertools
import logging
import os
import shutil
import sys
import tempfile

from pip._vendor import pkg_resources

import req_compile.compile
import req_compile.dists
import req_compile.metadata
import req_compile.repos.pypi

from req_compile import utils
from req_compile.compile import perform_compile
from req_compile.config import read_pip_default_index
from req_compile.repos.findlinks import FindLinksRepository
from req_compile.repos.pypi import PyPIRepository
from req_compile.repos.repository import CantUseReason, sort_candidates, NoCandidateException
from req_compile.repos.multi import MultiRepository
from req_compile.repos.solution import SolutionRepository
from req_compile.repos.source import SourceRepository
from req_compile.versions import is_possible

# Blacklist of requirements that will be filtered out of the output
BLACKLIST = [
]


def _cantusereason_to_text(reason):
    if reason == CantUseReason.VERSION_NO_SATISFY:
        return 'version mismatch'
    if reason == CantUseReason.WRONG_PLATFORM:
        return 'platform mismatch {}'.format(req_compile.repos.repository.PLATFORM_TAGS)
    if reason == CantUseReason.WRONG_PYTHON_VERSION:
        return 'python version/interpreter mismatch ({})'.format(', '.join(
            req_compile.repos.repository.RequiresPython.WHEEL_VERSION_TAGS))
    if reason == CantUseReason.IS_PRERELEASE:
        return 'prereleases not used'

    return 'unknown'


def _find_paths_to_root(failing_node, visited=None):
    if visited is None:
        visited = set()

    if not failing_node.reverse_deps:
        return [[failing_node]]

    paths = []
    for reverse_dep in failing_node.reverse_deps:
        if reverse_dep not in visited:
            new_visited = set(visited | {reverse_dep})
            new_paths = _find_paths_to_root(reverse_dep, visited=new_visited)
            for one_path in new_paths:
                one_path.append(failing_node)
                paths.append(one_path)

    return sorted(paths, key=len)


def _generate_no_candidate_display(req, repo, dists, failure):
    failing_node = dists[req.name]
    constraints = failing_node.build_constraints()
    can_satisfy = True
    if isinstance(failure, NoCandidateException):
        can_satisfy = is_possible(constraints)
        if not can_satisfy:
            print('No version could possibly satisfy the following requirements:',
                  file=sys.stderr)
        else:
            print('No version of {} could satisfy the following requirements ({}):'.format(req.name, constraints),
                  file=sys.stderr)
    else:
        print("A problem occurred while determining requirements for {name}:\n"
              "{failure}".format(name=req.name, failure=failure), file=sys.stderr)

    paths = _find_paths_to_root(failing_node)
    for path in paths:
        for idx, node in enumerate(path[:-1]):
            if idx > 0:
                if node.metadata is path[idx - 1].metadata:
                    continue
            node_str = node.metadata.to_definition((node.extra,) if node.extra else None)[0]
            print('  ' + node_str + ' → ', end='', file=sys.stderr)
        print(path[-2].dependencies[failing_node], file=sys.stderr)

    if can_satisfy:
        all_candidates = {repo: repo.get_candidates(req) for repo in repo}
        if sum(len(candidates) for candidates in all_candidates.values()) == 0:
            print('No candidates found in any of the input sources', file=sys.stderr)
        else:
            _dump_repo_candidates(req, repo)


def _dump_repo_candidates(req, repos):
    """
    Args:
        req (str):
        repos (Repository):
    """
    print('Found the following candidates, none of which will work:', file=sys.stderr)
    for repo in repos:
        candidates = repo.get_candidates(req)
        print('  {}:'.format(repo), file=sys.stderr)
        if candidates:
            attempted_versions = set()
            for num, candidate in enumerate(sort_candidates(candidates)):
                attempted_versions.add(candidate.version)
                if len(attempted_versions) > 3:
                    print('  -- Attempts stopped here ({} versions too '
                          'old to try)'.format(len(candidates) - num - 1), file=sys.stderr)
                    break
                try:
                    print('  {}: {}'.format(candidate,
                                            _cantusereason_to_text(
                                                repo.why_cant_I_use(req, candidate))),
                          file=sys.stderr)
                except req_compile.metadata.MetadataError:
                    print('  {}: {}'.format(candidate, 'Failed to parse metadata'), file=sys.stderr)
        else:
            print('  No candidates found', file=sys.stderr)


def _create_req_from_path(path, extras, extra_source_repos):
    """

    Args:
        path (str):

    Returns:

    """
    # Check if any extras were specified
    if '[' in path and path[-1] == ']':
        extra_idx = path.index('[')
        extras = extras or []
        extras += extras + [s.strip() for s in path[extra_idx + 1:-1].split(',')]
        path = path[:extra_idx]

    dist = req_compile.metadata.extract_metadata(path)
    if dist is None:
        raise ValueError(
            'Input arg "{}" is not directory containing setup.py or requirements file'.format(path))
    source_dist_name = dist.name
    if extras:
        source_dist_name += '[{}]'.format(','.join(extras))
    if extra_source_repos is not None:
        extra_source_repos.append(path)
    return [utils.parse_requirement('{}=={}'.format(source_dist_name, dist.version))]


def _create_input_reqs(input_arg, extras=None, extra_source_repos=None):
    input_arg = input_arg.strip()
    if input_arg == '-':
        stdin_contents = sys.stdin.readlines()

        def _create_stdin_input_req(line):
            try:
                return _create_input_reqs(line, extras=extras,
                                          extra_source_repos=extra_source_repos)
            except ValueError:
                return (utils.parse_requirement(line),)

        return list(itertools.chain(*[_create_stdin_input_req(line)
                                      for line in stdin_contents]))

    if os.path.isdir(input_arg):
        return _create_req_from_path(input_arg, extras, extra_source_repos)
    if os.path.isfile(input_arg):
        return utils.reqs_from_files([input_arg])
    return _create_req_from_path(input_arg, extras, extra_source_repos)


# pylint: disable=too-many-locals,too-many-branches
def run_compile(input_args,
                extras,
                constraint_files,
                repo,
                remove_source,
                annotate_source,
                no_comments,
                no_pins):
    """
    Args:
        input_args (list[str]):
        extras (Iterable[str]):
        constraint_files (list[str]):
        remove_source (bool):
        annotate_source (bool):
    Returns:

    """
    extra_sources = []
    if not input_args:
        if not sys.stdin.isatty():
            input_args = ('-',)
        else:
            input_args = ('.',)

    input_reqs = {
        input_arg: _create_input_reqs(input_arg, extras, extra_sources)
        for input_arg in input_args
    }
    if extra_sources:
        # remove_source = True
        # Add the sources provided to the search repos
        repo = MultiRepository(*([SourceRepository(source) for source in extra_sources] + [repo]))

    constraint_reqs = {}
    if constraint_files is not None:
        constraint_reqs = {
            input_arg: _create_input_reqs(input_arg, extras, extra_sources)
            for input_arg in constraint_files
        }

    try:
        results, roots = perform_compile(input_reqs, repo, extras=extras,
                                         constraint_reqs=constraint_reqs)

        def blacklist_filter(req):
            return req.metadata.name.lower() not in BLACKLIST

        req_filter = blacklist_filter
        if remove_source:
            if not any(isinstance(r, SourceRepository) for r in repo):
                raise ValueError('Cannot remove results from source, no source provided')

            def is_from_source(dist):
                return not isinstance(dist.metadata.origin, SourceRepository)

            req_filter = lambda req: blacklist_filter(req) and is_from_source(req)

        lines = sorted(results.generate_lines(roots, req_filter=req_filter),
                       key=lambda x: x[0][0].lower())

        fmt = '{key}'
        if not no_pins:
            fmt += '=={version}'
        if not no_comments:
            fmt += '  # {annotation}{constraints}'

        if annotate_source:
            repo_mapping = _annotate(input_reqs, repo)
        if lines:
            # left_column_len = max(len(x[0][0]) + len(x[0][1]) + 2 for x in lines)
            annotation = ''
            for line in lines:
                if annotate_source:
                    key = line[0][0]
                    source = results[key].metadata.origin
                    if source not in repo_mapping:
                        print('No repo for {}'.format(line), file=sys.stderr)
                        annotation = '[?] '
                    else:
                        annotation = '[{}] '.format(repo_mapping[source])

                print(fmt.format(key=line[0][0], version=line[0][1],
                                 annotation=annotation, constraints=line[1]))
    except (req_compile.repos.repository.NoCandidateException, req_compile.metadata.MetadataError) as ex:
        _generate_no_candidate_display(ex.req, repo, ex.results, ex)
        sys.exit(1)


def _annotate(input_reqs, repos):
    repo_mapping = {}
    qer_req = pkg_resources.working_set.find(pkg_resources.Requirement.parse('req_compile'))
    print('# Compiled by Qer Requirements Compiler ({}) on {} UTC'.format(
        qer_req.version if qer_req else 'dev',
        datetime.datetime.utcnow()))
    print('#')
    print('# Inputs:')
    for input_arg in input_reqs:
        input_to_print = input_arg
        if input_arg == '-':
            input_to_print = list(input_reqs[input_arg])
        elif os.path.exists(input_arg):
            input_to_print = os.path.abspath(input_arg)
        print('# {}'.format(input_to_print))
    print('#')
    print('# Repositories (this annotation produced by --annotate):')
    for idx, repo in enumerate(repos):
        repo_mapping[repo] = idx
        print('# [{}] {}'.format(idx, repo))
    print('')
    return repo_mapping


def build_repo(solutions, upgrade_packages,
               sources,
               find_links,
               index_urls, no_index, wheeldir,
               allow_prerelease=False):
    repos = []
    if solutions:
        repos.extend(SolutionRepository(solution, excluded_packages=upgrade_packages)
                     for solution in solutions)
    if sources:
        repos.extend(SourceRepository(source)
                     for source in sources)
    if find_links:
        repos.extend(FindLinksRepository(find_link, allow_prerelease=allow_prerelease)
                     for find_link in find_links)
    if not no_index:
        if not index_urls:
            default_index_url = read_pip_default_index() or 'https://pypi.org/simple'
            repos.append(
                PyPIRepository(default_index_url, wheeldir, allow_prerelease=allow_prerelease))
        else:
            repos.extend(PyPIRepository(index_url, wheeldir, allow_prerelease=allow_prerelease)
                         for index_url in index_urls)
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


def compile_main(args=None):
    logging.basicConfig(level=logging.ERROR)

    parser = argparse.ArgumentParser()
    group = parser.add_argument_group('requirement compilation')
    group.add_argument('requirement_files', nargs='*',
                       metavar='requirements_file',
                       help='Input requirements file or project directory to compile. Pass - to compile'
                            'from stdin')
    group.add_argument('-c', '--constraints', action='append',
                       metavar='constraints_file',
                       help='Constraints file or project directory to use as constraints. ')
    group.add_argument('-e', '--extra', action='append', dest='extras', default=[],
                       metavar='extra',
                       help='Extras to apply automatically to source packages')
    group.add_argument('-P', '--upgrade-package', action='append', dest='upgrade_packages',
                       metavar='package_name',
                       help='Package to omit from solutions. Use this to upgrade packages')
    group.add_argument('--remove-source', default=False, action='store_true',
                       help='Remove distributions satisfied via --source from the output')
    group.add_argument('-p', '--pre', dest='allow_prerelease', default=False, action='store_true',
                       help='Allow preleases from all sources')
    group.add_argument('--annotate', default=False, action='store_true',
                       help='Annotate the output file with the sources of each requirement')
    group.add_argument('--no-comments', default=False, action='store_true',
                       help='Disable comments in the output')
    group.add_argument('--no-pins', default=False, action='store_true',
                       help='Disable version pins, just list distributions')
    group.add_argument('-v', '--verbose', default=False, action='store_true',
                       help='Enable verbose output to stderr')
    add_repo_args(parser)

    args = parser.parse_args(args=args)
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)
        logging.getLogger('req_compile').setLevel(logging.DEBUG)

        logging.getLogger('req_compile.compile').addFilter(IndentFilter())

    wheeldir = args.wheel_dir
    if wheeldir:
        try:
            if not os.path.exists(wheeldir):
                os.mkdir(wheeldir)
        except OSError:
            pass
        delete_wheeldir = False
    else:
        wheeldir = tempfile.mkdtemp()
        delete_wheeldir = True

    try:
        repo = build_repo(args.solutions, args.upgrade_packages,
                          args.sources,
                          args.find_links, args.index_urls, args.no_index, wheeldir,
                          allow_prerelease=args.allow_prerelease)

        run_compile(args.requirement_files,
                    args.extras,
                    args.constraints if args.constraints else None,
                    repo,
                    args.remove_source,
                    args.annotate,
                    args.no_comments,
                    args.no_pins)
    finally:
        if delete_wheeldir:
            shutil.rmtree(wheeldir)


def add_repo_args(parser):
    group = parser.add_argument_group('repositories')
    group.add_argument('-n', '--solution', action='append', dest='solutions', default=[],
                       metavar='solution_file',
                       help='Existing fully-pinned constraints file to use as a baseline when compiling')
    group.add_argument('-s', '--source', action='append', dest='sources', default=[],
                       metavar='project_dir',
                       help='Search for projects in the provided directory recursively')
    group.add_argument('-f', '--find-links', action='append', default=[],
                       metavar='directory',
                       help='Directory to search for wheel and source distributions')
    group.add_argument('-i', '--index-url', action='append', dest='index_urls', default=[],
                       metavar='index_url',
                       help='Link to a remote index of python distributions (http or https)')
    group.add_argument('-w', '--wheel-dir', type=str, default=None,
                       metavar='wheel_dir',
                       help='Directory to which to download wheel and source distributions from remote index')
    group.add_argument('--no-index', action='store_true', default=False,
                       help='Do not connect to the internet to compile')


if __name__ == '__main__':
    compile_main()
