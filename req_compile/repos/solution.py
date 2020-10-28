from __future__ import print_function

import os
import sys

from six.moves import map as imap

import req_compile.containers
import req_compile.dists
import req_compile.utils
from req_compile.repos import RepositoryInitializationError
from req_compile.repos.repository import Candidate, DistributionType, Repository
from req_compile.repos.source import ReferenceSourceRepository


def _candidate_from_node(node):
    candidate = Candidate(
        node.key,
        node.metadata,
        node.metadata.version,
        None,
        None,
        "any",
        None,
        DistributionType.SOURCE,
    )
    candidate.preparsed = node.metadata
    return candidate


class SolutionRepository(Repository):
    def __init__(self, filename, excluded_packages=None):
        super(SolutionRepository, self).__init__("solution", allow_prerelease=True)
        self.filename = os.path.abspath(filename)
        self.excluded_packages = excluded_packages or []
        if excluded_packages:
            self.excluded_packages = [
                req_compile.utils.normalize_project_name(pkg)
                for pkg in excluded_packages
            ]
        if os.path.exists(filename) or filename == "-":
            self.solution = load_from_file(self.filename, origin=self)
        else:
            print("Solution file {} not found".format(filename), file=sys.stderr)
            self.solution = {}

    def __repr__(self):
        return "--solution {}".format(self.filename)

    def __eq__(self, other):
        return (
            isinstance(other, SolutionRepository)
            and super(SolutionRepository, self).__eq__(other)
            and self.filename == other.filename
        )

    def __hash__(self):
        return hash("solution") ^ hash(self.filename)

    def get_candidates(self, req):
        if req is None:
            return [_candidate_from_node(node) for node in self.solution]

        if req_compile.utils.normalize_project_name(req.name) in self.excluded_packages:
            return []

        try:
            node = self.solution[req.name]
            candidate = _candidate_from_node(node)
            return [candidate]
        except KeyError:
            return []

    def resolve_candidate(self, candidate):
        return candidate.preparsed, True

    def close(self):
        pass


def _parse_line(result, line, meta_file, origin):
    req_part, _, source_part = line.partition("#")
    req_part = req_part.strip()
    if not req_part:
        return

    req = req_compile.utils.parse_requirement(req_part)
    source_part = source_part.strip()

    if not source_part:
        raise RepositoryInitializationError(
            SolutionRepository,
            "Solution file {} is not fully annotated and cannot be used. Consider"
            " compiling the solution against a remote index to add annotations.".format(
                meta_file
            ),
        )

    if source_part[0] == "[":
        _, _, source_part = source_part.partition("] ")
    sources = source_part.split(", ")

    _add_sources(req, sources, result, origin)


def _add_sources(req, sources, result, origin):
    pkg_names = imap(lambda x: x.split(" ")[0], sources)
    constraints = imap(
        lambda x: x.split(" ")[1].replace("(", "").replace(")", "")
        if "(" in x
        else None,
        sources,
    )
    version = req_compile.utils.parse_version(list(req.specifier)[0].version)

    metadata = None
    if req.name in result:
        metadata = result[req.name].metadata
    if metadata is None:
        metadata = req_compile.containers.DistInfo(req.name, version, [])

    metadata.version = version
    metadata.origin = origin
    result.add_dist(metadata, None, req)
    for name, constraint in zip(pkg_names, constraints):
        if name and not (
            name.endswith(".txt")
            or name.endswith(".out")
            or "\\" in name
            or "/" in name
        ):
            constraint_req = req_compile.utils.parse_requirement(name)
            result.add_dist(constraint_req.name, None, constraint_req)
            reverse_dep = result[name]
            if reverse_dep.metadata is None:
                inner_meta = req_compile.containers.DistInfo(
                    constraint_req.name,
                    req_compile.utils.parse_version("0+missing"),
                    [],
                )
                inner_meta.origin = ReferenceSourceRepository(inner_meta)
                reverse_dep.metadata = inner_meta
        else:
            reverse_dep = None
        reason = _create_metadata_req(req, metadata, name, constraint)
        if reverse_dep is not None:
            reverse_dep.metadata.reqs.append(reason)
        result.add_dist(metadata.name, reverse_dep, reason)


def _create_metadata_req(req, metadata, name, constraints):
    marker = ""
    if "[" in name:
        extra = req_compile.utils.parse_requirement(name).extras[0]
        marker = ' ; extra == "{}"'.format(extra)

    return req_compile.utils.parse_requirement(
        "{}{}{}{}".format(
            metadata.name,
            ("[" + ",".join(req.extras) + "]") if req.extras else "",
            constraints if constraints else "",
            marker,
        )
    )


def load_from_file(filename, origin=None):
    result = req_compile.dists.DistributionCollection()

    if filename == "-":
        reqfile = sys.stdin
    else:
        reqfile = open(filename)

    try:
        for line in reqfile.readlines():
            _parse_line(result, line, filename, origin)
    finally:
        if reqfile is not sys.stdin:
            reqfile.close()

    _remove_nodes(result)
    return result


def _remove_nodes(result):
    nodes_to_remove = []
    for node in result:
        if node.metadata is None:
            nodes_to_remove.append(node)
    for node in nodes_to_remove:
        try:
            del result.nodes[node.key]
        except KeyError:
            pass
