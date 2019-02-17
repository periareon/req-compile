import os
import tarfile
import zipfile

import pkg_resources

from qer import utils
from qer.dists import DistInfo


def extract_metadata(dist, extras=()):
    """"""
    if dist.lower().endswith('.whl'):
        return _fetch_from_wheel(dist, extras=extras)
    if dist.lower().endswith('.zip'):
        return _fetch_from_zip(dist, extras=extras)
    elif dist.lower().endswith('.tar.gz'):
        return _fetch_from_source(dist, extras=extras)


def _fetch_from_zip(zip_file, extras):
    zfile = zipfile.ZipFile(zip_file, 'r')
    try:
        metadata_file = None
        pkg_info_file = None
        egg_info = None

        for name in zfile.namelist():
            if name.lower().endswith('pkg-info'):
                pkg_info_file = name
            elif name.lower().endswith('.egg-info'):
                egg_info = name
            elif name.lower().endswith('metadata'):
                metadata_file = name

        if egg_info:
            filename = os.path.basename(zip_file)
            name = '-'.join(filename.split('-')[0:-1])
            version = pkg_resources.parse_version(filename.split('-')[-1].replace('.tar.gz', ''))
            return _parse_requires_file(zip_file.extractfile(egg_info + '/requires.txt').read(),
                                        name,
                                        version,
                                        extras)

        if pkg_info_file:
            return _parse_flat_metadata(zfile.read(pkg_info_file).decode('utf-8'), extras)

        if metadata_file:
            return _parse_flat_metadata(zfile.read(metadata_file).decode('utf-8'), extras)
    finally:
        zfile.close()


def _fetch_from_source(tar_gz, extras):
    tar = tarfile.open(tar_gz, "r:gz")
    try:
        metadata_file = None
        pkg_info_file = None
        egg_info = None

        for info in tar.getmembers():
            name = info.name.lower()
            if name.endswith('pkg-info'):
                pkg_info_file = info.name
            elif name.endswith('.egg-info'):
                egg_info = info.name
            elif name.endswith('metadata'):
                metadata_file = info.name

        if egg_info:
            filename = os.path.basename(tar_gz)
            name = '-'.join(filename.split('-')[0:-1])
            version = pkg_resources.parse_version(filename.split('-')[-1].replace('.tar.gz', ''))
            requires_contents = ''
            try:
                requires_contents = tar.extractfile(egg_info + '/requires.txt').read().decode('utf-8')
            except KeyError:
                pass
            return _parse_requires_file(requires_contents,
                                        name,
                                        version,
                                        extras)

        if pkg_info_file:
            return _parse_flat_metadata(
                tar.extractfile(pkg_info_file).read().decode('utf-8'), extras)

        if metadata_file:
            return _parse_flat_metadata(
                tar.extractfile(metadata_file).read().decode('utf-8'), extras)
    finally:
        tar.close()


def _fetch_from_wheel(wheel, extras):
    zfile = zipfile.ZipFile(wheel, 'r')
    try:
        metadata_file = None
        infos = zfile.namelist()
        for info in infos:
            if info.lower().endswith('metadata'):
                metadata_file = info

        if metadata_file:
            return _parse_flat_metadata(zfile.read(metadata_file).decode('utf-8'), extras)
    finally:
        zfile.close()


def _parse_flat_metadata(contents, extras):
    name = None
    version = None
    raw_reqs = []

    for line in contents.split('\n'):
        if line.lower().startswith('name:'):
            name = line.split(':')[1].strip()
        if line.lower().startswith('version:'):
            version = pkg_resources.parse_version(line.split(':')[1].strip())
        if line.lower().startswith('requires-dist:'):
            raw_reqs.append(line.split(':')[1].strip())

    return DistInfo(name, version, list(utils.parse_requirements(raw_reqs)), extras=extras)


def _parse_requires_file(contents, name, version, extras):
    reqs = []
    sections = list(pkg_resources.split_sections(contents))
    for section in sections:
        if section[0] is None:
            reqs.extend(utils.parse_requirements(section[1]))
        elif section[0].startswith(':python_version'):
            for req in section[1]:
                reqs.append(utils.parse_requirement(req + ' ' + section[0].replace(':', ';')))

    return DistInfo(name, version, reqs)
