from __future__ import print_function

import os
import shutil
import subprocess
import sys
import tempfile
import time
from argparse import ArgumentParser

import pkg_resources


def run_qer_compile(reqfile, index_url=None):
    output_file, name = tempfile.mkstemp()
    subprocess.check_call([sys.executable, '-m', 'req_compile.cmdline', reqfile], stdout=output_file)
    os.close(output_file)
    return name


def run_pip_compile(reqfile, index_url=None):
    output_file, name = tempfile.mkstemp()
    os.close(output_file)
    # '--rebuild',
    subprocess.check_output([sys.executable, '-m', 'piptools', 'compile', reqfile, '-o', name, '--rebuild'])
    return name


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('requirements_file')
    parser.add_argument('-i', '--index-url', type=str, default=None)

    parsed_args = parser.parse_args()

    print('Compiling with Qer...', end='')
    sys.stdout.flush()
    start = time.time()
    qer_output_file = run_qer_compile(parsed_args.requirements_file)
    print(' DONE ({} seconds)'.format(time.time() - start))

    print('Compiling with pip-compile...', end='')
    sys.stdout.flush()
    start = time.time()
    pip_output_file = run_pip_compile(parsed_args.requirements_file)
    print(' DONE ({} seconds)'.format(time.time() - start))

    qer_line = None
    pip_line = None

    failed = False
    qer_handle = open(qer_output_file)
    pip_handle = open(pip_output_file)
    while True:
        if qer_line is None:
            qer_line = qer_handle.readline()
        if pip_line is None:
            pip_line = pip_handle.readline()

        if qer_line == '' or pip_line == '':
            break

        if qer_line.strip().startswith('#'):
            qer_line = None
        if pip_line.strip().startswith('#'):
            pip_line = None

        if pip_line is not None and qer_line is not None:
            qer_req = pkg_resources.Requirement.parse(qer_line)
            pip_req = pkg_resources.Requirement.parse(pip_line)

            if qer_req != pip_req:
                print('Requirement difference:\n{}{}'.format(qer_line, pip_line))
                failed = True
            qer_line = None
            pip_line = None

    qer_handle.close()
    pip_handle.close()

    if failed:
        shutil.move(qer_output_file, 'req_compile.txt')
        shutil.move(pip_output_file, 'pip.txt')
