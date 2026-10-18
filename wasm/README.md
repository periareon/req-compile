# The req-compile solver as a WebAssembly module

This directory builds `req_compile_solver.wasm`: the unmodified `req_compile`
package, its dependencies and the parts of the standard library it needs, running
on CPython 3.13 inside a WebAssembly module that imports nothing. Bazel can run
it with `module_ctx.execute_wasm`, which is how the `requirements` module extension
will resolve requirements without a host interpreter. The design is in
[docs/design/wasm_mode.md](../docs/design/wasm_mode.md).

## How it works

`execute_wasm` gives a module an input buffer and expects an output buffer back.
It provides no imports: no WASI, no filesystem, no clock, no network. Four small
pieces turn a stock CPython WASI build into something that runs in that box.

| File | Role |
| --- | --- |
| `wasi_stubs.c` | Defines every WASI function wasi-libc imports, inside the module. Standard output and error are captured into buffers, the clock is a counter, randomness is a fixed-seed generator so hashes are reproducible, and the filesystem is empty. |
| `shim.c` | Exports `allocate` and `solve` with the signatures Bazel expects. `solve` starts the interpreter, runs the bootstrap, hands over the input and returns what Python produced. Every call is a fresh instance, so nothing is torn down. |
| `bootstrap.py` | Runs during CPython's core initialization phase, when only builtin and frozen modules exist, and installs an importer over the bundle. The main phase then finds `encodings` there, and later everything else. |
| `bundle.py` | Packs the sources, or bytecode when a host Python 3.13 is available, into the bundle `embed.S` links into the module as data. |

`shims/` holds stand-ins for packages that `req_compile` imports but that cannot
work in the module: `requests` (nothing downloads), `toml` and `setuptools`
(no `pyproject.toml` or `setup.py` is ever evaluated), `multiprocessing` (one
thread) and `ctypes` (no dynamic loading, so the host is "not glibc").

The Python entry point is [`req_compile/wasm/entry.py`](../req_compile/wasm/entry.py).
It adapts the solver to *facts*: a dictionary of everything Bazel has read or
downloaded so far. A `FactRepository` serves index pages and metadata from the
facts and raises `NeedFacts` when something is missing, which ends the round. The
requests collected on the way, plus speculative ones for what the next rounds will
need, go back to Starlark, which performs them and calls again. The solver that
runs is `perform_compile_group`, the same one the command line uses.

## Building

Requirements: wasi-sdk 24, a CPython 3.13 `wasm32-wasi` build directory (such as
the `_build-python-3.13.*-wasi_sdk-24.zip` of
[brettcannon/cpython-wasi-build](https://github.com/brettcannon/cpython-wasi-build/releases),
which holds `libpython3.13.a`, `pyconfig.h` and the `Makefile`), the matching
CPython source tree and `Lib` directory, and a directory with `packaging` and
`overrides` unpacked. Optionally a host Python 3.13 to bundle bytecode, which makes
every call noticeably cheaper.

```bash
WASI_SDK=/opt/wasi-sdk-24.0 \
PY_BUILD=/path/to/cpython-wasi-build \
PY_SRC=/path/to/cpython \
PY_LIB=/path/to/python-3.13-wasi/lib/python3.13 \
PY_SITE=/path/to/site-packages \
BUNDLE_PYTHON=python3.13 \
wasm/build.sh
```

The result is `wasm/build/req_compile_solver.wasm`, about 16 MB, with no imports and
the exports `allocate`, `solve` and `_initialize`.

## Running it without Bazel

`run_local.py` calls the module the way Bazel does, through the `wasmtime` Python
package. `drive_local.py` is the round loop in Python: it reads files, downloads
index pages and metadata, and calls the module until it has a solution. It is the
reference for the Starlark loop in `req_compile/private/resolve.bzl` and a quick way to measure.

```bash
echo '{"op": "ping"}' | python run_local.py build/req_compile_solver.wasm
python drive_local.py build/req_compile_solver.wasm requirements.in \
    --platform manylinux_2_28_x86_64 --platform macosx_11_0_arm64 --python 3.11
```

## Running it in Bazel

The `requirements` module extension drives the module when a `parse` tag sets
`requirements_in`; the loop is `req_compile/private/resolve.bzl`. `example/` is a
workspace using it: copy the built module into it and run

```bash
bazel build //:uses_requests
```

It needs `--experimental_repository_ctx_execute_wasm`; with Bazel 10 and
`--experimental_repository_ctx_wasm_compilation` the module is compiled to JVM
bytecode instead of interpreted, which is several times faster. Without the flag
the extension fails with a message naming it, and hubs built from lock files are
unaffected either way.

The solution lands in `MODULE.bazel.lock` twice: as the repositories Bazel
instantiates, and as facts (`solution:<hub>` with the inputs it was solved from,
`meta:<sha256>` for every distribution consulted). An unchanged hub is rebuilt from
the facts without loading the module. A changed requirements file is re-solved
from the recorded versions, so only what the change touches is fetched. To start
over:

```bash
REQ_COMPILE_UPGRADE=all bazel mod deps
```

or name the packages to upgrade, comma separated.

## Measurements

Taken on an Apple M-series laptop against PyPI, October 2026.

| What | Result |
| --- | --- |
| Module size | 16 MB (10 MB of that is the bundle) |
| `ping` under wasmtime, source bundle | 0.35 s |
| `ping` under wasmtime, bytecode bundle | 0.05 s |
| `ping` in Bazel 9.3, interpreted | 60 s |
| `ping` in Bazel 10.0.0rc1, compiled, source bundle | 12.6 s |
| `ping` in Bazel 10.0.0rc1, compiled, bytecode bundle | 10.2 s |
| `requests` for one platform, host driver | 5 rounds, 4 s |
| `requests` for one platform, Bazel 9.3 interpreted, source bundle, one ingest call per document | 16 calls, 1006 s in the module, 1007 s elapsed |
| `requests` for one platform, Bazel 10 compiled, source bundle | 6 calls, 120 s in the module, 138 s elapsed |
| `requests` for one platform, Bazel 10 compiled, bytecode bundle | 6 calls, 97 s in the module, 99 s elapsed |
| `requests` for two platforms through the `requirements` extension (`example/`), Bazel 10 compiled, bytecode bundle | 5 calls, 107 s in the module, 117 s including fetching the wheels |
| Then adding `rich` (four new packages) to the same file | 7 calls, 134 s; the five existing packages keep their versions, their pages and metadata are not fetched |
| Then changing extension code without changing the requirements | 0 calls, the hub is rebuilt from the recorded solution in milliseconds |
| This repository's requirements for three platforms, host driver, starting from the checked-in pins | 4 rounds, 57 s, and the same 61, 56 and 58 versions as the three checked-in lock files |

`ping` is the floor of a call: interpreter start plus importing the solver. Under
Bazel's runtime that floor is seconds, not milliseconds, so the number of calls is
what matters, and the loop makes one call per round.
