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

if [ -n "${TRAMPOLINE:-}" ]; then
    PATCH="$HERE/patches/cpython-3.14-trampoline-interpreter.patch"
    if git apply --check --reverse "$PATCH" >/dev/null 2>&1; then
        echo "trampoline patch already applied"
    else
        echo "applying $(basename "$PATCH")"
        git apply "$PATCH"
    fi
    CONFIGURE_ARGS="${CONFIGURE_ARGS:-} --with-tail-call-interp"
fi

if [ -n "${CLEAN:-}" ]; then
    python3 Tools/wasm/wasi.py clean
fi

echo "building CPython for WASI (build python, then the wasm32-wasi host)"
# shellcheck disable=SC2086
WASI_SDK_PATH="$WASI_SDK" OPT="$OPT_ALL" python3 Tools/wasm/wasi.py build --quiet -- ${CONFIGURE_ARGS:-}

HOST="$CPYTHON_SRC/cross-build/wasm32-wasip1"
PY_VERSION="$(sed -n -E 's/^#define PY_MAJOR_VERSION[[:space:]]+([0-9]+).*/\1/p' Include/patchlevel.h).$(sed -n -E 's/^#define PY_MINOR_VERSION[[:space:]]+([0-9]+).*/\1/p' Include/patchlevel.h)"
echo "rebuilding Python/ceval.o for size"
(cd "$HOST" && rm -f Python/ceval.o && make -s Python/ceval.o OPT="$OPT_CEVAL" && rm -f "libpython$PY_VERSION.a" && make -s "libpython$PY_VERSION.a" OPT="$OPT_CEVAL")
ls -la "$HOST/libpython$PY_VERSION.a"
echo "PY_BUILD=$HOST PY_SRC=$CPYTHON_SRC PY_LIB=$CPYTHON_SRC/Lib"
