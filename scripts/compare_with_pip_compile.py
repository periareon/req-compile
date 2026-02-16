import os
import subprocess
import sys
import tempfile
import threading
import time
from argparse import ArgumentParser

import packaging.requirements
import packaging.version

from req_compile.containers import reqs_from_files
from req_compile.utils import normalize_project_name, has_prerelease


def run_qer_compile(reqfile, index_url=None):
    output_file, name = tempfile.mkstemp()
    error_file, error_name = tempfile.mkstemp()
    try:
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "req_compile",
                reqfile,
                "--wheel-dir",
                ".wheeldir",
                "--verbose",
            ],
            stdout=output_file,
            stderr=error_file,
        )
        os.lseek(output_file, 0, os.SEEK_SET)
        print(
            "\n" + os.read(output_file, 128000).decode("utf-8") + "\n", file=sys.stderr
        )
        return name
    except subprocess.CalledProcessError:
        os.lseek(error_file, 0, os.SEEK_SET)
        print(
            "\n" + os.read(error_file, 128000).decode("utf-8") + "\n", file=sys.stderr
        )
        raise
    finally:
        os.close(output_file)
        os.close(error_file)


def run_pip_compile(reqfile, index_url=None):
    output_file, name = tempfile.mkstemp()
    os.close(output_file)
    # '--rebuild',
    subprocess.check_output(
        [sys.executable, "-m", "piptools", "compile", reqfile, "-o", name]
    )
    return name


def filter_out_blacklist(req_set):
    return {
        req
        for req in req_set
        if req.name.lower()
        not in (
            "setuptools",
            "pip",
            "distutils",
            "distribute",
            "documenttemplate",
            "cython",
        )
    }


def normalize_reqs(req_set):
    return {
        packaging.requirements.Requirement(
            str(req).replace(req.name, normalize_project_name(req.name))
        )
        for req in req_set
    }


def do_qer(reqfile, results_queue):
    print("Compiling with Req-Compile...")
    qer_failed = False
    qer_output_file = None
    try:
        start = time.time()
        qer_output_file = run_qer_compile(reqfile)
        print(" DONE qer ({} seconds)".format(time.time() - start))
    except Exception:
        qer_failed = True
    results_queue.append((qer_output_file, qer_failed))


def do_pip(reqfile, results_queue):
    print("Compiling with pip-compile...")
    pip_failed = False
    pip_output_file = None
    try:
        start = time.time()
        pip_output_file = run_pip_compile(reqfile)
        print(" DONE pip ({} seconds)".format(time.time() - start))
    except Exception:
        pip_failed = True
    results_queue.append((pip_output_file, pip_failed))


def main():
    parser = ArgumentParser()
    parser.add_argument("requirements_file")
    parser.add_argument("-i", "--index-url", type=str, default=None)

    parsed_args = parser.parse_args()

    failed = True
    qer_output_file = None
    pip_output_file = None
    try:
        qer_queue = []
        qer_thread = threading.Thread(
            target=do_qer, args=(parsed_args.requirements_file, qer_queue)
        )
        qer_thread.start()

        pip_queue = []
        pip_thread = threading.Thread(
            target=do_pip, args=(parsed_args.requirements_file, pip_queue)
        )
        pip_thread.start()

        qer_thread.join()
        pip_thread.join()

        qer_output_file, qer_failed = qer_queue[0]
        pip_output_file, pip_failed = pip_queue[0]

        if qer_failed:
            if not pip_failed:
                print("Req-Compile failed but pip-tools did not")
                sys.exit(2)

        if pip_failed:
            if not qer_failed:
                print("Pip-compile failed but req-compile did not")
                sys.exit(3)

        if not (qer_failed or pip_failed):
            failed = False
            qer_reqs = filter_out_blacklist(set(reqs_from_files([qer_output_file])))
            pip_reqs = filter_out_blacklist(set(reqs_from_files([pip_output_file])))

            qer_reqs = normalize_reqs(qer_reqs)
            pip_reqs = normalize_reqs(pip_reqs)

            if any(has_prerelease(req) for req in pip_reqs):
                print("Skipping because pip-compile resolved a pre-release")
                sys.exit(0)

            if qer_reqs != pip_reqs:
                print("Reqs do not match!")
                qer_only = qer_reqs - pip_reqs

                pip_only = pip_reqs - qer_reqs

                for qer_req in set(qer_only):
                    print("Validating {}".format(qer_req))
                    matching_pip_req = [
                        req for req in pip_only if req.name == qer_req.name
                    ]
                    for req in matching_pip_req:
                        qver = packaging.version.Version(
                            next(iter(qer_req.specifier)).version
                        )
                        pver = packaging.version.Version(
                            next(iter(req.specifier)).version
                        )

                        print("Comparing versions {} {}".format(qver, pver))

                        if qver == pver:
                            print("They matched, removing both")
                            qer_only.remove(qer_req)
                            pip_only.remove(req)

                if qer_only or pip_only:
                    print("Qer only reqs: {}".format(qer_only))
                    print("Pip only reqs: {}".format(pip_only))
                    sys.exit(1)
        else:
            sys.exit(0)
    except Exception as ex:
        print("Failed due to: {} {}".format(ex.__class__, ex))
    finally:
        if qer_output_file:
            os.remove(qer_output_file)
        if pip_output_file:
            os.remove(pip_output_file)


if __name__ == "__main__":
    main()
