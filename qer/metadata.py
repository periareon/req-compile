import tarfile
import zipfile
import functools

import pkg_resources

from qer import pypi


class DistInfo(object):
    def __init__(self):
        self.reqs = []
        self.name = None
        self.version = None

    def __repr__(self):
        return self.name + ' ' + self.version + '\n' + '\n'.join([str(req) for req in self.reqs])


def extract_metadata(dist):
    """"""
    if dist.lower().endswith('.whl'):
        return _fetch_from_wheel(dist)
    elif dist.lower().endswith('.tar.gz'):
        return _fetch_from_source(dist)


def _fetch_from_source(tar_gz):
    tar = tarfile.open(tar_gz, "r:gz")
    try:
        metadata_file = None
        for info in tar.getmembers():
            name = info.name
            if name.lower().endswith('pkg-info') or name.lower().endswith('metadata') or name.lower().endswith('metadata.json'):
                metadata_file = name

        if metadata_file:
            return _parse_flat_metadata(tar.extractfile(metadata_file).read())
    finally:
        tar.close()


def _fetch_from_wheel(wheel):
    zfile = zipfile.ZipFile(wheel, 'r')
    try:
        metadata_file = None
        infos = zfile.namelist()
        for info in infos:
            if info.lower().endswith('metadata') or info.lower().endswith('metadata.json'):
                metadata_file = info

        if metadata_file:
            return _parse_flat_metadata(zfile.read(metadata_file))
    finally:
        zfile.close()


def _parse_flat_metadata(contents):
    result = DistInfo()
    raw_reqs = []
    for line in contents.split('\n'):
        if line.lower().startswith('name:'):
            result.name = line.split(':')[1].strip()
        if line.lower().startswith('version:'):
            result.version = pkg_resources.parse_version(line.split(':')[1].strip())
        if line.lower().startswith('requires-dist:'):
            raw_reqs.append(line.split(':')[1].strip())

    result.reqs = list(pkg_resources.parse_requirements(raw_reqs))
    return result


# if __name__ == '__main__':
#     print extract_metadata(pypi.download_candidate('pylint'))
