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
# Required environment:
#   WASI_SDK      a wasi-sdk checkout (24 is what this was developed with)
#   CPYTHON_SRC   a CPython 3.13 source tree (a git checkout of the 3.13 branch)
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

cd "$CPYTHON_SRC"
echo "building CPython for WASI (build python, then the wasm32-wasi host)"
WASI_SDK_PATH="$WASI_SDK" OPT="$OPT_ALL" python3 Tools/wasm/wasi.py build --quiet

HOST="$CPYTHON_SRC/cross-build/wasm32-wasip1"
echo "rebuilding Python/ceval.o for size"
(cd "$HOST" && rm -f Python/ceval.o && make -s Python/ceval.o OPT="$OPT_CEVAL" && rm -f libpython3.13.a && make -s libpython3.13.a OPT="$OPT_CEVAL")
ls -la "$HOST/libpython3.13.a"
echo "PY_BUILD=$HOST PY_SRC=$CPYTHON_SRC PY_LIB=$CPYTHON_SRC/Lib"
