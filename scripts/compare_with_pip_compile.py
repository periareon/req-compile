from __future__ import print_function

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from argparse import ArgumentParser

import pkg_resources

from req_compile.utils import reqs_from_files, normalize_project_name


def run_qer_compile(reqfile, index_url=None):
    output_file, name = tempfile.mkstemp()
    subprocess.check_call([sys.executable, '-m', 'req_compile.cmdline', reqfile, '--wheel-dir', '.wheeldir'], stdout=output_file)
    os.lseek(output_file, 0, os.SEEK_SET)
    print('\n' + os.read(output_file, 128000).decode('utf-8') + '\n', file=sys.stderr)
    os.close(output_file)
    return name


def run_pip_compile(reqfile, index_url=None):
    output_file, name = tempfile.mkstemp()
    os.close(output_file)
    # '--rebuild',
    subprocess.check_output([sys.executable, '-m', 'piptools', 'compile', reqfile, '-o', name])
    return name


def filter_out_blacklist(req_set):
    return {req for req in req_set
            if req.name not in ('setuptools', 'pip', 'distutils', 'distribute')}


def normalize_reqs(req_set):
    return {pkg_resources.Requirement.parse(str(req).replace(req.name, normalize_project_name(req.name)))
            for req in req_set}


def do_qer(reqfile, results_queue):
    print('Compiling with Req-Compile...')
    qer_failed = False
    qer_output_file = None
    try:
        start = time.time()
        qer_output_file = run_qer_compile(reqfile)
        print(' DONE qer ({} seconds)'.format(time.time() - start))
    except Exception:
        qer_failed = True
    results_queue.append((qer_output_file, qer_failed))


def do_pip(reqfile, results_queue):
    print('Compiling with pip-compile...')
    pip_failed = False
    pip_output_file = None
    try:
        start = time.time()
        pip_output_file = run_pip_compile(reqfile)
        print(' DONE pip ({} seconds)'.format(time.time() - start))
    except Exception:
        pip_failed = True
    results_queue.append((pip_output_file, pip_failed))


def main():
    parser = ArgumentParser()
    parser.add_argument('requirements_file')
    parser.add_argument('-i', '--index-url', type=str, default=None)

    parsed_args = parser.parse_args()

    failed = True
    qer_output_file = None
    pip_output_file = None
    try:
        qer_queue = []
        qer_thread = threading.Thread(target=do_qer, args=(parsed_args.requirements_file, qer_queue))
        qer_thread.start()

        pip_queue = []
        pip_thread = threading.Thread(target=do_pip, args=(parsed_args.requirements_file, pip_queue))
        pip_thread.start()

        qer_thread.join()
        pip_thread.join()

        qer_output_file, qer_failed = qer_queue[0]
        pip_output_file, pip_failed = pip_queue[0]

        if qer_failed:
            if not pip_failed:
                raise ValueError('Req-Compile failed but pip-tools did not')

        if not (qer_failed or pip_failed):
            qer_line = None
            pip_line = None

            failed = False
            qer_reqs = filter_out_blacklist(set(reqs_from_files([qer_output_file])))
            pip_reqs = filter_out_blacklist(set(reqs_from_files([pip_output_file])))

            qer_reqs = normalize_reqs(qer_reqs)
            pip_reqs = normalize_reqs(pip_reqs)

            if qer_reqs != pip_reqs:
                print('Reqs do not match!')
                qer_only = qer_reqs - pip_reqs

                pip_only = pip_reqs - qer_reqs

                for qer_req in set(qer_only):
                    print('Validating {}'.format(qer_req))
                    matching_pip_req = [
                        req for req in pip_only if req.name == qer_req.name
                    ]
                    for req in matching_pip_req:
                        qver = pkg_resources.parse_version(next(iter(qer_req.specifier)).version)
                        pver = pkg_resources.parse_version(next(iter(req.specifier)).version)

                        print('Comparing versions {} {}'.format(qver, pver))

                        if qver == pver:
                            print('They matched, removing both')
                            qer_only.remove(qer_req)
                            pip_only.remove(req)

                if qer_only or pip_only:
                    print('Qer only reqs: {}'.format(qer_only))
                    print('Pip only reqs: {}'.format(pip_only))
                    failed = True
        else:
            sys.exit(0)
    except Exception as ex:
        print('Failed due to: {} {}'.format(ex.__class__, ex))
        failed = True
    finally:
        if failed:
            if qer_output_file:
                shutil.move(qer_output_file, 'req_compile.txt')
            if pip_output_file:
                shutil.move(pip_output_file, 'pip.txt')
        else:
            if qer_output_file:
                os.remove(qer_output_file)
            if pip_output_file:
                os.remove(pip_output_file)

    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
