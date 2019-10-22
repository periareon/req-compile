# -*- coding: utf-8 -*-
from __future__ import print_function
from __future__ import with_statement

import os
from setuptools import setup


def file_contents(file_name):
    curr_dir = os.path.abspath(os.path.dirname(__file__))
    with open(os.path.join(curr_dir, file_name)) as the_file:
        contents = the_file.read()
    return contents


def get_version():
    curr_dir = os.path.abspath(os.path.dirname(__file__))
    with open(curr_dir + "/newline_req/__init__.py", "r") as init_version:
        for line in init_version:
            if "__version__" in line:
                return str(line.split("=")[-1].strip(" ")[1:-2])


setup(
    name='newline-req',
    version=get_version(),
    python_requires=">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*",
    install_requires=file_contents("requirements.txt"),
    tests_require=["awacs>=0.8"],
    extras_require={'policy': ['awacs>=0.8']},
)
