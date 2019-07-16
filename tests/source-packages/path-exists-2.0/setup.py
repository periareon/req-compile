import os
import json
import setuptools

METADATA_FILENAME = os.path.join('path-exists', 'package_metadata.json')

if os.path.exists(METADATA_FILENAME):
    with open(METADATA_FILENAME) as fh:
        metadata = json.load(fh)

setuptools.setup(
    name='path-exists',
    version=metadata["version"]
)
