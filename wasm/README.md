# The req-compile solver as a WebAssembly module

This directory builds `req_compile_solver.wasm`: the unmodified `req_compile`
package, its dependencies and the parts of the standard library it needs, running
on CPython 3.14 inside a WebAssembly module that imports nothing. Bazel can run
it with `module_ctx.execute_wasm`, which is how the `requirements` module extension
resolves requirements without a host interpreter. The design is in
[docs/design/wasm_mode.md](../docs/design/wasm_mode.md).

## How it works

`execute_wasm` gives a module an input buffer and expects an output buffer back.
It provides no imports: no WASI, no filesystem, no clock, no network. The module
is built by [rules_venv](https://github.com/periareon/rules_venv)'s `py_wasm_module`
(`//wasm:req_compile_solver` in `BUILD.bazel`), which turns a CPython WASI
build into something that runs in that box: it defines every WASI function the
interpreter imports inside the module (standard output and error are captured,
the clock is a counter, randomness is a fixed-seed generator, the filesystem is
empty), serves every import from a bundle of bytecode linked into the module,
freezes the `encodings` modules the interpreter needs before that importer
exists, exports `allocate` and one function per entry of `exports`, and
pre-initializes the module with Wizer so that a call finds the interpreter
already running. Its documentation describes the calling convention; it is the
one `execute_wasm` expects.

This repository supplies what goes inside:

| Target or file | Role |
| --- | --- |
| [`req_compile/wasm/exports.py`](../req_compile/wasm/exports.py) | The entry module. Its `solve` is the module's one export: it takes the input of a call as `bytes` and returns the output and the return code. |
| [`req_compile/wasm/entry.py`](../req_compile/wasm/entry.py) | The Python side of the protocol, which `solve` dispatches to (below). |
| `//req_compile:wasm_solver` | The solver's sources with only the dependencies that work in the module, `packaging` and `overrides`. |
| `//wasm:shims` | Stand-ins for the packages `req_compile` imports but that cannot work in the module: `requests` (nothing downloads), `toml` and `setuptools` (no `pyproject.toml` or `setup.py` is ever evaluated), `multiprocessing` (one thread) and `ctypes` (no dynamic loading, so the host is "not glibc"). |

`entry.py` adapts the solver to *facts*: a dictionary of everything Bazel has read
or downloaded so far. A `FactRepository` serves index pages and metadata from the
facts and raises `NeedFacts` when something is missing, which ends the round. The
requests collected on the way, plus speculative ones for what the next rounds will
need, go back to Starlark, which performs them and calls again. The solver that
runs is `perform_compile_group`, the same one the command line uses.

## Building

```bash
bazel build //wasm:req_compile_solver
```

The output is `req_compile_solver.wasm`, about 28 MB; `bazel cquery
--output=files //wasm:req_compile_solver` prints its path, which is not under
the `bazel-bin` link because the module is built in a Python 3.14 configuration.
The build fetches, the first time, what the `py_wasm_toolchain` in
`//wasm/toolchain` is made of: the `trampoline` CPython `wasm32-wasi` build of
[periareon/cpython-wasi-build](https://github.com/periareon/cpython-wasi-build)
(declared in `MODULE.bazel`, by hash; see "Where the time goes" for why not the
stock build) and, from rules_venv's own toolchain, the wasi-sdk release that
built it and Wizer. Its bytecode comes from the hermetic Python 3.14 toolchain
of this repository, which is the same minor version. The toolchain exists for
the hosts rules_venv has a wasi-sdk for, Linux and macOS,
on x86_64 and arm64; the target is `manual`, so `//...` leaves it alone. The
same inputs give the same module. CI builds it on Linux and macOS for every
change, and the release workflow builds it to attach the module to each release,
whose `requirements` extension downloads it the first time a hub resolves.

A CPython built differently is a `py_wasm_toolchain` of one's own, registered
ahead of rules_venv's; see "Toolchains" in rules_venv's `python/wasm/defs.bzl`.

## Running it without Bazel

`run_local.py` calls the module the way Bazel does, through the `wasmtime` Python
package. `drive_local.py` is the round loop in Python: it reads files, downloads
index pages and metadata, and calls the module until it has a solution. It is the
reference for the Starlark loop in `req_compile/private/resolve.bzl` and a quick way to measure.

```bash
MODULE="$(bazel cquery --output=files //wasm:req_compile_solver)"
echo '{"op": "ping"}' | python wasm/run_local.py "$MODULE"
python wasm/drive_local.py "$MODULE" wasm/example/requirements.in \
    --platform manylinux_2_28_x86_64 --platform macosx_11_0_arm64 --python 3.11
```

## Running it in Bazel

The `requirements` module extension drives the module for every `resolve` tag; the loop is `req_compile/private/resolve.bzl`. `example/` is a
workspace using it: copy the built module into it and run

```bash
cp "$(bazel cquery --output=files //wasm:req_compile_solver)" wasm/example/
cd wasm/example && bazel build //:uses_requests
```

It needs `--experimental_repository_ctx_execute_wasm`; with Bazel 10 and
`--experimental_repository_ctx_wasm_compilation` the module is compiled to JVM
bytecode instead of interpreted, which is several times faster. Without the flag
the extension fails with a message naming it, and hubs built from lock files are
unaffected either way.

The solution lands in `MODULE.bazel.lock` twice: as the repositories Bazel
instantiates, and as facts (`solution:<hub>` with the inputs it was solved from,
`meta:<sha256>` for every distribution consulted). An unchanged hub is rebuilt from
the facts without loading the module. A changed requirements file, included
files too, is re-solved from the recorded versions, so only what the change
touches is fetched. To move a pin on purpose:

```bash
REQ_COMPILE_UPGRADE=<package> bazel run @pip_deps//:requirements.update
```

Several names may follow, comma separated; `all` upgrades every package. The
extension reads the variable and resolves those packages again from the index,
ignoring their pins in the file, and the update writes the result. A hub with no
`requirements_txt` has only the lock to move: `REQ_COMPILE_UPGRADE=<package>
bazel mod deps` (or any build that needs the hub). The lock records the file as
it was when the hub resolved, before the update rewrote it; the next Bazel
command brings it up to date, or `bazel mod deps --lockfile_mode=update` at once.

### Dependabot

`example/requirements.txt` is the hub's pinned file, named by `requirements_txt`
on the tag: what `requirements.in` resolved to, one entry per package with its
version and the sha256 of every artifact the hub's platforms use, in the shape
`pip-compile --generate-hashes` writes. `bazel run @pip_deps//:requirements.update`
writes it and `bazel test //:requirements.test` fails while it is out of date
(`//:requirements.test` is a `test_suite` in `example/BUILD.bazel` around
`@pip_deps//:requirements.test`, which sits in the hub repository where
`bazel test //...` would not reach it; the file needs no `exports_files`).
Dependabot's `pip` updater bumps versions and hashes in it; fed back to the hub,
the file is what an existing lock is to pip-compile: each package keeps its
pinned version while `requirements.in` allows it, so the bump is what the next
resolution uses, a bound raised in `requirements.in` moves the pin by itself,
and a package newly added to `requirements.in` resolves freely and then appears
in the file. `example/.github/` holds a `dependabot.yml` and a workflow
that, on Dependabot pull requests, rewrites the file in the hub's format and
refreshes `MODULE.bazel.lock`, which is needed because both files are recorded
inputs of the lock.

A fully pinned file can also be fed as `requirements_in` directly; then
`enforce_hashes` (the default) applies the rules of `pip --require-hashes`: a
version bumped without its hash fails to resolve, and so does any package the
file pins no hash for.

## Measurements

Taken on an Apple M-series laptop against PyPI, October 2026. The module is
built with the trampoline interpreter, the last rows; the rows "after the
optimization pass" are what the stock CPython build gives, and the ones about a
compiled evaluation loop what a size-optimized build gives (see "Where the time
goes").

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
| After the optimization pass (snapshot, less Python per call): `ping` | 0.0 s |
| After the optimization pass: ingest of a 1.8 MB page | 1.1 s (was 16 s) |
| After the optimization pass: solve of 61 packages for three platforms, all facts present | 88 s (was 273 s) |
| After the optimization pass: adding `rich` | 7 calls, 33 s elapsed (was 139 s) |
| After the optimization pass: fresh resolve of both example hubs, no facts | 4 calls, 45 s in the module (was 70 s elapsed) |
| With the evaluation loop compiled (CPython built size-optimized, see below): solve of 61 packages for three platforms | 8.9 s; 5.6 s, 3.5 s, 4.6 s over three calls with the JIT flags of `example/.bazelrc` |
| With the evaluation loop compiled: ingest of a 1.8 MB page | 0.3 s |
| With the evaluation loop compiled: fresh resolve of both example hubs, no facts | 4 calls, 4.5 s in the module, 13 s elapsed |
| With the evaluation loop compiled: adding `rich` | 7 calls, 3.4 s in the module, 4.6 s elapsed |
| With the trampoline interpreter (CPython 3.14 with the patch described below): solve of 61 packages for three platforms | 3.2 s, 2.6 s, 2.5 s over three calls; 2.2 s, 1.4 s, 1.3 s with the JIT flags |
| With the trampoline interpreter: ingest of a 1.8 MB page | 0.1 s |
| With the trampoline interpreter: fresh resolve of both example hubs, no facts | 4 calls, 1.6 s in the module, 15 s elapsed, most of it fetching the wheels |
| With the trampoline interpreter: adding `rich` | 7 calls, 1.3 s in the module, 2.0 s elapsed |
| The same under wasmtime, for scale: solve of 61 packages for three platforms | 0.27 s with the switch interpreter, 0.57 s with the trampoline |
| This repository's requirements for three platforms, host driver, starting from the checked-in pins | 4 rounds, 57 s, and the same 61, 56 and 58 versions as the three checked-in lock files |

## Where the time goes

Bazel runs the module with Chicory. With `--experimental_repository_ctx_wasm_compilation`
Chicory compiles each wasm function to a JVM method, except functions too large
for one method, which it interprets silently. Asking Chicory directly (`MachineFactoryCompiler`
with `InterpreterFallback.WARN`, against Bazel's own jar) names them for this
module: `_PyEval_EvalFrameDefault`, CPython's bytecode loop, and
`_PyUnicode_InitStaticStrings`, which only runs at start-up. So every Python
bytecode the solver executes is interpreted twice over, by CPython and by Chicory,
while the C helpers (`_json`, `_sre`, the allocator) run compiled. Measured against
wasmtime the ratio is a few hundred to one for Python-heavy work.

That shaped the optimizations, in order of effect:

- **Pre-initialization with Wizer.** The ten-second floor of every call was
  CPython starting and importing some 190 modules; the snapshot makes it zero.
- **Less Python per call.** Candidates are built once per index page and shared by
  the repositories of all platforms; `Requires-Python` and wheel tags are checked
  once per distinct value; artifacts that can never install on a platform are
  left out once rather than rejected on every request (keeping one non-pre-release
  so the solver's pre-release policy is unchanged); index pages with absolute
  URLs skip `urljoin`. The solver's own results are identical.
- **One call per round**, with documents ingested inside the solve call.

A Flight Recorder profile of a full solve under Bazel's Chicory confirmed the
diagnosis: 92% of samples had the interpreter on the stack and 3% were in
compiled code. The evaluation loop was 66 KB of wasm in the stock `-O3` build,
just over what fits in one JVM method. So the last step was to make it fit:
CPython built size-optimized, with `ceval.c` compiled with `-Oz
-fno-inline-functions -mllvm -ir-outliner`, brings the function to 52 KB,
provided nothing is optimized again at link time (`-O2` there pushed it back
over the limit; `py_wasm_module` links without it). Chicory then compiles every
function, and the full solve dropped from 88 s to 9 s.

That is not the end of it, because a second interpreter sits underneath: the
evaluation loop is then a 60 KB JVM method, and HotSpot runs such a method in its
own bytecode interpreter. `-XX:+PrintCompilation` shows why: the huge-method
limit skips it by default; with that lifted, C1 gives up ("out of virtual
registers") and C2 gives up on its node budget ("out of nodes"). Raising the
budget (`-XX:MaxNodeLimit=2000000 -XX:NodeLimitFudgeFactor=100000`) lets C2
compile it. In a long-lived JVM a solve call then takes 1.6 s instead of 8.5 s
once the JIT has warmed, which takes two or three calls. Inside Bazel the gain
is smaller because each extension evaluation starts from a cold class and C2
recompiles the method a few times before it settles: the same solve measured
5.6 s, 3.5 s and 4.6 s over three consecutive calls, against 8.9 s without the
flags.

The better answer is to not have a 60 KB function at all, and CPython 3.14
nearly provides it. Its tail-calling interpreter (`--with-tail-call-interp`)
generates one C function per bytecode instruction, each ending in a tail call to
the next. As is, it cannot be used here: it needs the `preserve_none` calling
convention and guaranteed tail calls, which clang does not have for wasm, and
Chicory compiles a wasm tail call as call-plus-return, which would overflow the
stack. A patch of 170 lines of macro changes
(`cpython-3.14-trampoline-interpreter.patch`, in this repository's history under
`wasm/patches/`) keeps the generated per-instruction functions and turns each tail call
into a return to a small loop that calls the next handler: a call-threaded
interpreter. The evaluation loop is then 328 bytes of wasm and the largest of
the 234 handlers is 1.5 KB, far from both the JVM method limit and HotSpot's
huge-method limit, and HotSpot compiles the hot handlers on its own. The price is
a call and a return per bytecode: under wasmtime the full solve takes 0.57 s
against 0.27 s with the switch interpreter. Under Chicory it is the other way
round, 2.5 s against 8.9 s with default JVM flags and 1.3 s against 3.5 to
4.6 s with them. That CPython is built and released by
[periareon/cpython-wasi-build](https://github.com/periareon/cpython-wasi-build),
as the `trampoline` variant beside `stock` and `small-eval` (the size-optimized
build of the previous paragraph), in the archive layout rules_venv's toolchains
consume; `//wasm/toolchain` assembles a `py_wasm_toolchain` from it and
rules_venv's wasi-sdk and Wizer, and `MODULE.bazel` registers it ahead of
rules_venv's default, as a dev dependency since only this repository builds the
module. With the stock CPython of rules_venv's own toolchain the same module
solves in 88 s.

One JVM flag still pays with the trampoline. Other CPython functions exceed
HotSpot's 8,000-byte huge-method limit, and letting the JIT compile them takes a
warm solve call from 3.1 s to 1.9 s in a long-lived JVM; the node-budget flags
no longer change anything, since the method they were for is gone. It is a
server JVM option, so it goes in `.bazelrc` as a startup flag; `example/.bazelrc`
has it:

```
startup --host_jvm_args=-XX:-DontCompileHugeMethods
```
