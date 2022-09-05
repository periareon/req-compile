# coding=utf-8
from __future__ import print_function

import argparse
import datetime
import logging
import os
import shutil
import sys
import tempfile
from collections import OrderedDict
from itertools import groupby, repeat
from typing import IO, Iterable, List, Mapping, Optional, Sequence, Set

import pkg_resources

import req_compile.compile
import req_compile.dists
import req_compile.errors
import req_compile.metadata
import req_compile.metadata.metadata
import req_compile.repos.pypi
from req_compile import utils
from req_compile.compile import perform_compile
from req_compile.config import read_pip_default_index
from req_compile.containers import DistInfo, RequirementContainer, RequirementsFile
from req_compile.errors import NoCandidateException
from req_compile.repos.findlinks import FindLinksRepository
from req_compile.repos.multi import MultiRepository
from req_compile.repos.pypi import IndexType, PyPIRepository
from req_compile.repos.repository import (
    CantUseReason,
    Repository,
    RepositoryInitializationError,
    sort_candidates,
)
from req_compile.repos.solution import (
    DependencyNode,
    DistributionCollection,
    SolutionRepository,
)
from req_compile.repos.source import SourceRepository
from req_compile.utils import parse_requirement
from req_compile.versions import is_possible

# Blacklist of requirements that will be filtered out of the output
BLACKLIST = []  # type: Iterable[str]


def _cantusereason_to_text(
    reason: CantUseReason,
) -> str:  # pylint: disable=too-many-return-statements
    if reason == CantUseReason.VERSION_NO_SATISFY:
        return "version mismatch"
    if reason == CantUseReason.WRONG_PLATFORM:
        return "platform mismatch"
    if reason == CantUseReason.WRONG_PYTHON_VERSION:
        return "python version/interpreter mismatch"
    if reason == CantUseReason.IS_PRERELEASE:
        return "prereleases not used"
    if reason == CantUseReason.BAD_METADATA:
        return "bad metadata"
    if reason == CantUseReason.NAME_DOESNT_MATCH:
        return "name doesn't match"
    if reason == CantUseReason.WRONG_ABI:
        return "extension ABI mismatch"
    return f"unknown ({reason})"


def _find_paths_to_root(
    failing_node: DependencyNode, visited: Set[DependencyNode] = None
) -> Sequence[Sequence[DependencyNode]]:
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
                tail_path = list(one_path)
                tail_path.append(failing_node)
                paths.append(tail_path)

    return sorted(paths, key=len)


def _generate_no_candidate_display(
    req: pkg_resources.Requirement,
    repo: Repository,
    dists: DistributionCollection,
    failure: Exception,
) -> None:
    """Print a human friendly display to stderr when compilation fails"""
    failing_node = dists[req.name]
    constraints = failing_node.build_constraints()

    can_satisfy = True
    no_candidates = False

    if isinstance(failure, NoCandidateException):
        try:
            can_satisfy = is_possible(constraints)
        except (ValueError, TypeError):
            can_satisfy = True

        all_candidates = {repo: repo.get_candidates(req) for repo in repo}
        no_candidates = (
            sum(len(list(candidates)) for candidates in all_candidates.values()) == 0
        )

        if not can_satisfy:
            print(
                "No version of {} could possibly satisfy the following requirements ({}):".format(
                    req.name, constraints
                ),
                file=sys.stderr,
            )
        elif no_candidates:
            print(
                "No candidates found for {} in any of the input sources. Required by:".format(
                    req.name
                ),
                file=sys.stderr,
            )
        elif not constraints.specifier:
            print(
                "No working candidates found for {}. Required by:".format(req.name),
                file=sys.stderr,
            )
        else:
            print(
                "No version of {} could satisfy the following requirements ({}):".format(
                    req.project_name, constraints
                ),
                file=sys.stderr,
            )
    else:
        print(
            "A problem occurred while determining requirements for {name}:\n"
            "{failure}".format(name=req.project_name, failure=failure),
            file=sys.stderr,
        )

    paths = _find_paths_to_root(failing_node)
    _print_paths_to_root(failing_node, paths, True)

    if can_satisfy and not no_candidates:
        _dump_repo_candidates(req, repo)


def _print_paths_to_root(
    failing_node: DependencyNode,
    paths: Iterable[Sequence[DependencyNode]],
    require_specifier: bool = True,
) -> None:
    """
    Given a failing node, print to stderr all the nodes that required it. If any have
    constraints, prefer printing only these first.
    """
    printed_constraints = False
    nodes_visited = set()
    for path in paths:
        failing_dep = path[-2].dependencies[failing_node]
        if not require_specifier or (failing_dep is not None and failing_dep.specifier):
            if path[-2] in nodes_visited:
                continue

            printed_constraints = True
            nodes_visited.add(path[-2])

            print("  ", end="", file=sys.stderr)
            for node in path[:-1]:
                if node.metadata is None:
                    node_str = node.key + "[UNKNOWN]"
                else:
                    node_str = "{}{}{}".format(
                        node.metadata.name,
                        "[{}]".format(",".join(node.extras)) if node.extras else "",
                        (" " + str(node.metadata.version))
                        if node.metadata is not None
                        and node.metadata.version is not None
                        else "",
                    )
                if node_str == "-":
                    node_str = "<stdin>"
                print(node_str + " -> ", end="", file=sys.stderr)
            print(path[-2].dependencies[failing_node], file=sys.stderr)

    # If there were no constraints on this failing node, at least print who required it
    if not printed_constraints and require_specifier:
        _print_paths_to_root(failing_node, paths, require_specifier=False)


def _dump_repo_candidates(
    req: pkg_resources.Requirement, repos: Iterable[Repository]
) -> None:
    """
    Args:
        req (str):
        repos (Repository):
    """
    print("Found the following candidates, none of which will work:", file=sys.stderr)
    for repo in repos:
        candidates = list(repo.get_candidates(req))
        print("  {}:".format(repo), file=sys.stderr)
        if candidates:
            attempted_versions = set()
            for num, candidate in enumerate(sort_candidates(candidates)):
                attempted_versions.add(candidate.version)
                if len(attempted_versions) > req_compile.compile.MAX_DOWNGRADE:
                    too_old_count = len(candidates) - num
                    if too_old_count:
                        print(
                            "  -- Attempts stopped here ({} versions too "
                            "old to try)".format(too_old_count),
                            file=sys.stderr,
                        )
                    break
                try:
                    print(
                        "  {}: {}".format(
                            candidate,
                            _cantusereason_to_text(repo.why_cant_I_use(req, candidate)),
                        ),
                        file=sys.stderr,
                    )
                except req_compile.errors.MetadataError:
                    print(
                        "  {}: {}".format(candidate, "Failed to parse metadata"),
                        file=sys.stderr,
                    )
        else:
            print("  No candidates found", file=sys.stderr)


def _create_req_from_path(path: str) -> RequirementContainer:
    """

    Args:
        path (str):

    Returns:

    """
    try:
        dist = req_compile.metadata.extract_metadata(path)
    except req_compile.errors.MetadataError:
        dist = None

    if dist is None:
        raise ValueError(
            'Input arg "{}" is not a directory containing a valid setup.py or pyproject.toml'.format(
                path
            )
        )
    return dist


def _create_input_reqs(
    input_arg: str, extra_sources: List[str]
) -> RequirementContainer:
    input_arg = input_arg.strip()
    if input_arg == "-":
        stdin_contents = sys.stdin.readlines()

        def _create_stdin_input_req(line: str) -> Optional[pkg_resources.Requirement]:
            try:
                result = _create_req_from_path(line)
                extra_sources.append(line)
                return utils.parse_requirement(
                    "{}=={}".format(*result.to_definition(None))
                )
            except ValueError:
                try:
                    return utils.parse_requirement(line)
                except ValueError:
                    return None

        reqs = (
            _create_stdin_input_req(line.strip())
            for line in stdin_contents
            if line.strip()
        )
        non_none_reqs = (req for req in reqs if req is not None)
        return DistInfo("-", None, non_none_reqs, meta=True)

    if os.path.isfile(input_arg):
        return RequirementsFile.from_file(input_arg)

    return _create_req_from_path(input_arg)


def _blacklist_filter(req: DependencyNode) -> bool:
    """Return false if this requirement is not allowed."""
    return req.key.lower() not in BLACKLIST


def _is_not_from_source(dist: DependencyNode) -> bool:
    return (
        dist.metadata is not None
        and dist.metadata.origin is not None
        and not isinstance(dist.metadata.origin, SourceRepository)
    )


def _source_req_filter(req: DependencyNode) -> bool:
    return _blacklist_filter(req) and _is_not_from_source(req)


def _non_source_req_filter(req: DependencyNode) -> bool:
    return _blacklist_filter(req) and not _is_not_from_source(req)


def write_requirements_file(
    results: DistributionCollection,
    roots: Set[DependencyNode],
    repo: Repository,
    annotate_source: bool = False,
    input_reqs: Iterable[RequirementContainer] = None,
    remove_non_source: bool = False,
    remove_source: bool = False,
    no_pins: bool = False,
    no_comments: bool = False,
    hashes: bool = False,
    write_to: IO[str] = sys.stdout,
) -> None:
    """
    Write a text requirements file with various options

    Args:
        results (DistributionCollection): Results of a compilation
        roots (set[DependencyNode]): Roots to include in the output. Anything not reachable from these
            roots will be discarded
        annotate_source (bool): if True, annotates where a requirement comes from via a comment header
            and numeric indicators per line. Also includes information about the input requirements in the header
        input_reqs (list[RequirementContainer]): If annotate_source is true, the input requirements must be
            provided to display them in the header
        repo (Repository): The repository that was the source of the requirements. In the case of annotate_source,
            all requirements will belong to this repository unless it is a MultiRepository
        remove_non_source (bool): Requirements that don't come from source directories will be omitted
        remove_source (bool): Requirements that come from source directories will be omitted
        no_pins (bool): If True, omit the solved version from the requirement lines
        no_comments (bool): If True, omit the comment containing the reverse dependencies
        write_to (file-like object): Object that implements "write" that takes a string
    """
    req_filter = _blacklist_filter
    if remove_source or remove_non_source:
        if not any(isinstance(r, SourceRepository) for r in repo):
            raise ValueError("Cannot remove results from source, no source provided.")

        if remove_non_source:
            req_filter = _non_source_req_filter
        else:
            req_filter = _source_req_filter

    if hashes:
        _write_index_directives(list(repo), write_to)
        for node in sorted(
            results.visit_nodes(roots),
            key=lambda x: str(x.metadata and x.metadata.name.lower()),
        ):
            if node.metadata is None:
                continue
            if node.metadata.meta or not req_filter(node):
                continue

            write_to.write(f"{node.metadata.name}=={node.metadata.version}")
            if hashes and node.metadata.hash:
                write_to.write(" \\\n")
                write_to.write("    --hash=")
                write_to.write(node.metadata.hash)

            constraints = req_compile.dists.build_constraints(node)
            all_constraints = list(constraints)
            if all_constraints:
                write_to.write("\n")
                if len(all_constraints) == 1:
                    write_to.write(f"    # via {all_constraints[0]}\n")
                else:
                    write_to.write("    # via\n")
                    for constraint in sorted(constraints, key=lambda val: val.lower()):
                        write_to.write("    #   ")
                        write_to.write(constraint)
                        write_to.write("\n")
            else:
                write_to.write("\n")
    else:
        lines = sorted(
            results.generate_lines(roots, req_filter=req_filter, strip_extras=True),
            key=lambda x: x[0][0].lower(),
        )

        # pylint: disable=unnecessary-lambda-assignment
        fmt = "{key}"
        line_len = lambda x: len(x[0][0])
        if not no_pins:
            fmt += "=={version}"
            line_len = lambda x: len(x[0][0]) + len(str(x[0][1]))
        if hashes:
            fmt += " --hash={hash}"
            line_len = lambda x: len(x[0][0]) + len(str(x[0][1])) + 8 + len(x[0][2])
        if not no_comments:
            fmt += "{padding}# {annotation}{constraints}"
        if annotate_source:
            if input_reqs is None:
                raise ValueError(
                    "Input requirements are required if annotating source."
                )
            repo_mapping = _generate_repo_header(input_reqs, list(repo), write_to)
        else:
            _write_index_directives(list(repo), write_to)
        if lines:
            left_column_len = max(line_len(x) + 2 for x in lines)
            annotation = ""
            for line in lines:
                if annotate_source:
                    key = line[0][0]
                    source_meta = results[key].metadata
                    assert source_meta is not None

                    source = source_meta.origin
                    if source is None or source not in repo_mapping:
                        annotation = "[?] "
                    else:
                        annotation = "[{}] ".format(repo_mapping[source])

                padding = " " * (left_column_len - line_len(line))
                write_to.write(
                    fmt.format(
                        key=line[0][0],
                        version=line[0][1],
                        hash=line[0][2],
                        padding=padding,
                        annotation=annotation,
                        constraints=line[1],
                    )
                )
                write_to.write("\n")


def _generate_repo_header(
    input_reqs: Iterable[RequirementContainer],
    repos: Sequence[Repository],
    write_to: IO[str],
) -> Mapping[Repository, int]:
    """Generate the header used in --annotate mode. Produces a mapping from repo to integer to mark
    each line
    """
    repo_mapping = {}
    qer_req = pkg_resources.working_set.find(
        pkg_resources.Requirement.parse("req_compile")
    )
    write_to.write(
        "# Compiled by Req-Compile ({}) on {} UTC\n".format(
            qer_req.version if qer_req else "dev", datetime.datetime.utcnow()
        )
    )
    write_to.write("#\n# Inputs:\n")
    for input_arg in input_reqs:
        input_to_print = input_arg.name
        if input_arg == "-":
            input_to_print = ", ".join(
                [
                    str(req)
                    for req in sorted(list(input_arg.reqs), key=lambda req: req.name)
                ]
            )
        write_to.write("# {}\n".format(input_to_print))
    write_to.write("#\n# Repositories (this annotation produced by --annotate):\n")
    for idx, repo in enumerate(repos):
        repo_mapping[repo] = idx
        write_to.write("# [{}] {}\n".format(idx, repo))
    write_to.write("\n")
    return repo_mapping


def _write_index_directives(repos: Sequence[Repository], write_to: IO[str]) -> None:
    """Write the --index-url and --extra-index-url lines in the requirement files.

    Args:
        repos: All repos used in the solution.
        write_to: Output to write to.
    """
    wrote_any = False
    for repo in repos:
        if isinstance(repo, PyPIRepository) and repo.index_type != IndexType.DEFAULT:
            wrote_any = True
            write_to.write(str(repo) + "\n")

    if wrote_any:
        write_to.write("\n")


def build_repo(
    solutions: Iterable[str],
    upgrade_packages: Iterable[str],
    sources: Iterable[str],
    excluded_sources: Iterable[str],
    find_links: Iterable[str],
    index_urls: Iterable[str],
    wheeldir: str,
    extra_index_urls: Iterable[str] = None,
    no_index: bool = False,
    allow_prerelease: bool = False,
) -> Repository:
    repos: List[Repository] = []
    if solutions:
        repos.extend(
            SolutionRepository(solution, excluded_packages=upgrade_packages)
            for solution in solutions
        )
    if sources:
        repos.extend(
            SourceRepository(source, excluded_paths=excluded_sources)
            for source in sources
        )
    if find_links:
        repos.extend(
            FindLinksRepository(find_link, allow_prerelease=allow_prerelease)
            for find_link in find_links
        )
    if not no_index:
        if not index_urls:
            default_index_url = read_pip_default_index() or "https://pypi.org/simple"
            repos.append(
                PyPIRepository(
                    default_index_url,
                    wheeldir,
                    allow_prerelease=allow_prerelease,
                    index_type=IndexType.DEFAULT,
                )
            )
        else:
            repos.extend(
                PyPIRepository(
                    index_url,
                    wheeldir,
                    allow_prerelease=allow_prerelease,
                    index_type=IndexType.INDEX_URL,
                )
                for index_url in index_urls
            )
        if extra_index_urls is not None:
            repos.extend(
                PyPIRepository(
                    index_url,
                    wheeldir,
                    allow_prerelease=allow_prerelease,
                    index_type=IndexType.EXTRA_INDEX_URL,
                )
                for index_url in extra_index_urls
            )
    if not repos:
        raise ValueError("At least one Python distributions source must be provided.")
    if len(repos) > 1:
        repo: Repository = MultiRepository(*repos)
    else:
        repo = repos[0]
    return repo


class IndentFilter(logging.Filter):
    """A filter to indent to a level specified by the depth attribute of a logging record"""

    def filter(self, record: logging.LogRecord) -> bool:
        depth = getattr(record, "depth", 0)
        record.msg = (" " * depth) + record.msg
        return True


def compile_main(raw_args: Sequence[str] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Req-Compile: Python requirements compiler"
    )
    group = parser.add_argument_group("requirement compilation")
    group.add_argument(
        "requirement_files",
        nargs="*",
        metavar="requirements_file",
        help="Input requirements file or project directory to compile. Pass - to compile"
        "from stdin",
    )
    group.add_argument(
        "-c",
        "--constraints",
        action="append",
        metavar="constraints_file",
        help="Constraints file or project directory to use as constraints. ",
    )
    group.add_argument(
        "-e",
        "--extra",
        action="append",
        dest="extras",
        default=[],
        metavar="extra",
        help="Extras to apply automatically to source packages",
    )
    group.add_argument(
        "-P",
        "--upgrade-package",
        action="append",
        dest="upgrade_packages",
        metavar="package_name",
        help="Package to omit from solutions. Use this to upgrade packages",
    )
    group.add_argument(
        "--remove-source",
        default=False,
        action="store_true",
        help="Remove distributions satisfied via --source from the output",
    )
    group.add_argument(
        "--remove-non-source",
        default=False,
        action="store_true",
        help="Remove distributions not satisfied via --source from the output",
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
        "--annotate",
        default=False,
        action="store_true",
        help="Annotate the output file with the sources of each requirement",
    )
    group.add_argument(
        "--no-comments",
        default=False,
        action="store_true",
        help="Disable comments in the output",
    )
    group.add_argument(
        "--no-pins",
        default=False,
        action="store_true",
        help="Disable version pins, just list distributions",
    )
    group.add_argument(
        "--hashes,--generate-hashes",
        dest="hashes",
        action="store_true",
        help="Write hashes of the exact files used during solving to the solution",
    )
    add_logging_args(parser)
    add_repo_args(parser)

    args = parser.parse_args(args=raw_args)
    logger = logging.getLogger("req_compile")

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)
        logger.setLevel(logging.DEBUG)

        logger.getChild("compile").addFilter(IndentFilter())
    else:
        logging.basicConfig(level=logging.CRITICAL, stream=sys.stderr)

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

    input_args = args.requirement_files
    if not input_args:
        # Check to see whether stdin is hooked up to piped data or the console
        if not sys.stdin.isatty():
            input_args = ("-",)
        else:
            input_args = (".",)

    extra_sources: List[str] = []
    input_reqs = [
        _create_input_reqs(input_arg, extra_sources) for input_arg in input_args
    ]

    for req in list(input_reqs):
        if isinstance(req, RequirementsFile):
            req_param_parser = argparse.ArgumentParser()
            add_repo_args(req_param_parser)
            req_param_parser.add_argument(
                "-e",
                "--editable",
                dest="editable_sources",
                action="append",
                default=[],
                help="A local project directory",
            )

            req_args = req_param_parser.parse_args(req.parameters)

            all_index_urls = OrderedDict(zip(args.index_urls, repeat(None)))
            for url in req_args.index_urls:
                all_index_urls[url] = None
            args.index_urls = list(all_index_urls)

            all_extra_index_urls = OrderedDict(zip(args.extra_index_urls, repeat(None)))
            for url in req_args.extra_index_urls:
                all_extra_index_urls[url] = None
            args.extra_index_urls = list(all_extra_index_urls)

            for editable_source in req_args.editable_sources:
                input_reqs.append(_create_req_from_path(editable_source))
            extra_sources += req_args.editable_sources

    constraint_reqs = []
    if args.constraints is not None:
        constraint_reqs = [
            _create_input_reqs(input_arg, extra_sources)
            for input_arg in args.constraints
        ]

    if args.extras:
        for req in input_reqs:
            try:
                extra_req = pkg_resources.Requirement.parse(
                    req.name + "[{}]".format(",".join(args.extras))
                )
            except pkg_resources.RequirementParseError:  # type: ignore[attr-defined]
                continue
            extra_constraint = DistInfo(
                "{}-extra".format(req.name), None, [extra_req], meta=True
            )
            constraint_reqs.append(extra_constraint)

    repo = build_repo(
        args.solutions,
        args.upgrade_packages,
        extra_sources + args.sources,
        args.excluded_sources,
        args.find_links,
        args.index_urls,
        wheeldir,
        extra_index_urls=args.extra_index_urls,
        no_index=args.no_index,
        allow_prerelease=args.allow_prerelease,
    )
    try:
        results, roots = perform_compile(
            input_reqs, repo, extras=args.extras, constraint_reqs=constraint_reqs
        )
    except RepositoryInitializationError as ex:
        logger.exception("Error initialization repository")
        print("Error initializing {}: {}".format(ex.type.__name__, ex), file=sys.stderr)
        sys.exit(1)
    except req_compile.errors.NoCandidateException as ex:
        assert ex.results is not None
        _generate_no_candidate_display(ex.req, repo, ex.results, ex)
        sys.exit(1)
    except req_compile.errors.MetadataError as ex:
        assert ex.results is not None
        _generate_no_candidate_display(parse_requirement(ex.name), repo, ex.results, ex)
        sys.exit(1)
    finally:
        if delete_wheeldir:
            shutil.rmtree(wheeldir)

    write_requirements_file(
        results,
        roots,
        annotate_source=args.annotate,
        input_reqs=input_reqs,
        repo=repo,
        remove_non_source=args.remove_non_source,
        remove_source=args.remove_source,
        no_pins=args.no_pins,
        no_comments=args.no_comments,
        hashes=args.hashes,
    )


def add_logging_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-v",
        "--verbose",
        default=False,
        action="store_true",
        help="Enable verbose output to stderr",
    )


def norm_index_url(index_url: str) -> str:
    """Removing trailing slashes from index URLs"""
    return index_url.rstrip("/")


def add_repo_args(parser: argparse.ArgumentParser) -> None:
    """Add arguments related to adding repositories to the command line"""
    group = parser.add_argument_group("repositories")
    group.add_argument(
        "-n",
        "--solution",
        action="append",
        dest="solutions",
        default=[],
        metavar="solution_file",
        help="Existing fully-pinned constraints file to use as a baseline when compiling",
    )
    group.add_argument(
        "-s",
        "--source",
        action="append",
        dest="sources",
        default=[],
        metavar="project_dir",
        help="Search for projects in the provided directory recursively",
    )
    group.add_argument(
        "-x",
        "--exclude-source",
        action="append",
        dest="excluded_sources",
        default=[],
        help="Directories to exclude when searching for projects. Applies recursively",
    )
    group.add_argument(
        "-f",
        "--find-links",
        action="append",
        default=[],
        metavar="directory",
        help="Directory to search for wheel and source distributions",
    )
    group.add_argument(
        "-i",
        "--index-url",
        action="append",
        dest="index_urls",
        default=[],
        type=norm_index_url,
        metavar="index_url",
        help="Link to a remote index of python distributions (http or https)",
    )
    group.add_argument(
        "--extra-index-url",
        action="append",
        dest="extra_index_urls",
        default=[],
        type=norm_index_url,
        metavar="extra_index_url",
        help="Extra Index URLs, to be searched first.",
    )
    group.add_argument(
        "-w",
        "--wheel-dir",
        type=str,
        default=None,
        metavar="wheel_dir",
        help="Directory to which to download wheel and source distributions from remote index",
    )
    group.add_argument(
        "--no-index",
        action="store_true",
        default=False,
        help="Do not connect to the internet to compile",
    )


if __name__ == "__main__":
    compile_main()
