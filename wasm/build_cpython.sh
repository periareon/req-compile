#!/bin/bash
# Build CPython for wasm32-wasi the way the solver module needs it.
#
# Bazel runs the module with Chicory, which compiles every wasm function to a
# JVM method except those too large for one, which it interprets. CPython's
# evaluation loop, `_PyEval_EvalFrameDefault`, is just over that size in a
# normal build, and interpreting it costs the solver most of its time. Built
# for size, with inlining off and LLVM's IR outliner on for `ceval.c`, the
# function fits and Chicory compiles it; everything the solver runs is then
# compiled code.
#
# Optional:
#   CONFIGURE_ARGS  extra arguments for CPython's configure
#   TRAMPOLINE=1    (3.14 or newer) apply patches/cpython-3.14-trampoline-interpreter.patch
#                   and build the call-threaded interpreter: one function per
#                   instruction, so no function is anywhere near the JVM method limit
#   CLEAN=1         remove previous build output first (needed when configure arguments change)
#
# Required environment:
#   WASI_SDK      a wasi-sdk checkout (24 is what this was developed with)
#   CPYTHON_SRC   a CPython source tree (a git checkout of the 3.13 or 3.14 branch)
# Output: $CPYTHON_SRC/cross-build/wasm32-wasip1, to pass to build.sh as PY_BUILD,
# with PY_SRC=$CPYTHON_SRC and PY_LIB=$CPYTHON_SRC/Lib.
set -euo pipefail

: "${WASI_SDK:?set WASI_SDK}"
: "${CPYTHON_SRC:?set CPYTHON_SRC}"

# Size-optimized throughout; the solver's hot code is Python bytecode, and the
# C it runs is faster compiled at -Os than interpreted at -O3.
OPT_ALL="${OPT_ALL:--DNDEBUG -Os}"
# What it takes to get the evaluation loop under the JVM method size limit.
OPT_CEVAL="${OPT_CEVAL:--DNDEBUG -Oz -fno-inline-functions -mllvm -ir-outliner}"

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$CPYTHON_SRC"

# The tail-call flag goes to the wasm host build only: the native interpreter
# CPython builds first, to run its own build, is compiled by the host compiler,
# which generally lacks `preserve_none`.
HOST_CONFIGURE_ARGS=""
if [ -n "${TRAMPOLINE:-}" ]; then
    PATCH="$HERE/patches/cpython-3.14-trampoline-interpreter.patch"
    # `patch` rather than `git apply`: the source tree may sit inside another
    # repository's checkout, where `git apply` resolves paths against the wrong
    # root and reports the wrong state.
    if patch -p1 -N -s --dry-run < "$PATCH" >/dev/null 2>&1; then
        echo "applying $(basename "$PATCH")"
        patch -p1 -N -s < "$PATCH"
    elif patch -p1 -R -s --dry-run < "$PATCH" >/dev/null 2>&1; then
        echo "trampoline patch already applied"
    else
        echo "error: $(basename "$PATCH") does not apply to $CPYTHON_SRC" >&2
        exit 1
    fi
    HOST_CONFIGURE_ARGS="--with-tail-call-interp"
fi

# CPython's WASI build driver: a package from 3.14 on (its `wasi.py` wrapper
# only runs under a recent Python), a script before.
if [ -d Tools/wasm/wasi ]; then
    WASI_PY=Tools/wasm/wasi
else
    WASI_PY=Tools/wasm/wasi.py
fi

if [ -n "${CLEAN:-}" ]; then
    python3 "$WASI_PY" clean
fi

echo "building CPython's native build interpreter"
python3 "$WASI_PY" configure-build-python
python3 "$WASI_PY" make-build-python
echo "building CPython for wasm32-wasi"
# shellcheck disable=SC2086
WASI_SDK_PATH="$WASI_SDK" OPT="$OPT_ALL" python3 "$WASI_PY" configure-host -- ${CONFIGURE_ARGS:-} $HOST_CONFIGURE_ARGS
WASI_SDK_PATH="$WASI_SDK" OPT="$OPT_ALL" python3 "$WASI_PY" make-host

HOST="$CPYTHON_SRC/cross-build/wasm32-wasip1"
PY_VERSION="$(sed -n -E 's/^#define PY_MAJOR_VERSION[[:space:]]+([0-9]+).*/\1/p' Include/patchlevel.h).$(sed -n -E 's/^#define PY_MINOR_VERSION[[:space:]]+([0-9]+).*/\1/p' Include/patchlevel.h)"
echo "rebuilding Python/ceval.o for size"
(cd "$HOST" && rm -f Python/ceval.o && make -s Python/ceval.o OPT="$OPT_CEVAL" && rm -f "libpython$PY_VERSION.a" && make -s "libpython$PY_VERSION.a" OPT="$OPT_CEVAL")
ls -la "$HOST/libpython$PY_VERSION.a"
echo "PY_BUILD=$HOST PY_SRC=$CPYTHON_SRC PY_LIB=$CPYTHON_SRC/Lib"
