import zipfile
from contextlib import closing

from req_compile import utils
from req_compile.dists import DistInfo


def _fetch_from_wheel(wheel):
    zfile = zipfile.ZipFile(wheel, 'r')
    with closing(zfile):
        infos = zfile.namelist()
        for info in infos:
            if info.endswith('.dist-info/METADATA'):
                return _parse_flat_metadata(zfile.read(info).decode('utf-8', 'ignore'))

        return None


def _parse_flat_metadata(contents):
    name = None
    version = None
    raw_reqs = []

    for line in contents.split('\n'):
        lower_line = line.lower()
        if name is None and lower_line.startswith('name:'):
            name = line.split(':')[1].strip()
        elif version is None and lower_line.startswith('version:'):
            version = utils.parse_version(line.split(':')[1].strip())
        elif lower_line.startswith('requires-dist:'):
            raw_reqs.append(line.partition(':')[2].strip())

    return DistInfo(name, version, list(utils.parse_requirements(raw_reqs)))
