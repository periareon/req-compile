from collections import defaultdict

from six.moves import map as imap

import qer.dists
import qer.utils


def load_from_file(filename):
    result = qer.dists.DistributionCollection()

    req_mapping = defaultdict(lambda: defaultdict(list))

    with open(filename) as reqfile:
        for line in reqfile.readlines():
            req_part, _, source_part = line.partition('#')
            req = qer.utils.parse_requirement(req_part)
            source_part = source_part.strip()

            sources = source_part.split(', ')

            pkg_names = imap(lambda x: x.split(' ')[0], sources)
            constraints = imap(lambda x: x.split(' ')[1].replace('(', '').replace(')', '') if '(' in x else None, sources)

            version = qer.utils.parse_version(list(req.specifier)[0].version)
            metadata = qer.dists.DistInfo(req.name, version, [], req.extras)

            for name, constraints in zip(pkg_names, constraints):
                if not name or name.endswith('.txt') or name.endswith('.out'):
                    name = None
                else:
                    req_mapping[name][metadata.name].append(constraints)
                    name = name.split('[')[0]
                result.add_dist(metadata, name)

    for root_req in req_mapping:
        for req in req_mapping[root_req]:
            req_constraints = req_mapping[root_req][req][0] or ''
            if '[' in root_req:
                req_name, extras = root_req.split('[')
                extras = extras.replace(']', '')
                extras = extras.split(',')
                for extra in extras:
                    result.dists[qer.utils.normalize_project_name(req_name)].metadata.reqs.append(
                        qer.utils.parse_requirement(req + req_constraints + ' ; extra=="{}"'.format(extra)))
            else:
                result.dists[qer.utils.normalize_project_name(root_req)].metadata.reqs.append(qer.utils.parse_requirement(req + req_constraints))
    return result
