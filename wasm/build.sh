#!/bin/bash
# Build the req-compile WebAssembly solver from the unmodified Python sources.
#
# Required environment:
#   WASI_SDK      a wasi-sdk 24 checkout
#   PY_BUILD      a CPython wasm32-wasi build directory (libpython3.X.a, pyconfig.h, Makefile)
#   PY_SRC        the matching CPython source tree (Include/, Modules/)
#   PY_LIB        the matching CPython Lib directory of pure-Python modules
#   PY_SITE       a directory holding `packaging/` and `overrides/`
#   BUNDLE_PYTHON optional: a host Python of the embedded minor version, to bundle bytecode
#   LINK_FLAGS    optional: link-time flags, default `-Wl,--strip-all`; "" keeps function names
#   WIZER         optional: path to `wizer`, to pre-initialize the interpreter at build time
# Output: $OUT (default: build/req_compile_solver.wasm next to this script)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
BUILD="${BUILD_DIR:-$HERE/build}"
OUT="${OUT:-$BUILD/req_compile_solver.wasm}"
CC="$WASI_SDK/bin/clang"
AR="$WASI_SDK/bin/llvm-ar"
mkdir -p "$BUILD/extra" "$(dirname "$OUT")"

# The Python version of the build, e.g. 3.14, from the source tree.
PY_VERSION="$(sed -n -E 's/^#define PY_MAJOR_VERSION[[:space:]]+([0-9]+).*/\1/p' "$PY_SRC/Include/patchlevel.h").$(sed -n -E 's/^#define PY_MINOR_VERSION[[:space:]]+([0-9]+).*/\1/p' "$PY_SRC/Include/patchlevel.h")"
LIBPYTHON="$PY_BUILD/libpython$PY_VERSION.a"
echo "building against Python $PY_VERSION ($LIBPYTHON)"

CFLAGS=(--target=wasm32-wasi -O2 -DNDEBUG -I"$PY_BUILD" -I"$PY_SRC/Include")

# 1. The vendored libraries libpython depends on but the archive does not contain.
#    A CPython build directory has them compiled already (with the right flags
#    and file list); otherwise compile them from the sources.
if [ ! -f "$BUILD/extra/libextra.a" ] && ls "$PY_BUILD"/Modules/_decimal/libmpdec/*.o >/dev/null 2>&1; then
    echo "collecting libmpdec, expat and hacl objects from the CPython build"
    "$AR" rcs "$BUILD/extra/libextra.a" "$PY_BUILD"/Modules/_decimal/libmpdec/*.o "$PY_BUILD"/Modules/expat/*.o "$PY_BUILD"/Modules/_hacl/*.o
fi
if [ ! -f "$BUILD/extra/libextra.a" ]; then
    echo "compiling libmpdec, expat and hacl"
    LIBFLAGS=("${CFLAGS[@]}" -std=c11 -D_BSD_SOURCE -D_DEFAULT_SOURCE -I"$PY_SRC/Include/internal" -Wno-everything)
    for f in "$PY_SRC"/Modules/_decimal/libmpdec/*.c; do
        case "$f" in *bench*|*examples*) continue ;; esac
        "$CC" "${LIBFLAGS[@]}" -I"$PY_SRC/Modules/_decimal/libmpdec" -DCONFIG_32=1 -DANSI=1 -c "$f" -o "$BUILD/extra/mpdec_$(basename "$f" .c).o"
    done
    for f in "$PY_SRC"/Modules/expat/xmlparse.c "$PY_SRC"/Modules/expat/xmlrole.c "$PY_SRC"/Modules/expat/xmltok.c; do
        "$CC" "${LIBFLAGS[@]}" -I"$PY_SRC/Modules/expat" -DHAVE_EXPAT_CONFIG_H -c "$f" -o "$BUILD/extra/expat_$(basename "$f" .c).o"
    done
    for f in "$PY_SRC"/Modules/_hacl/*.c; do
        case "$f" in *Simd*) continue ;; esac
        "$CC" "${LIBFLAGS[@]}" -I"$PY_SRC/Modules/_hacl/include" -I"$PY_SRC/Modules/_hacl/internal" -c "$f" -o "$BUILD/extra/hacl_$(basename "$f" .c).o"
    done
    "$AR" rcs "$BUILD/extra/libextra.a" "$BUILD"/extra/*.o
fi

# 2. The bundle of Python sources: stdlib, dependencies, shims and req_compile itself.
echo "bundling sources"
STAGE="$BUILD/stage"
rm -rf "$STAGE" && mkdir -p "$STAGE"
cp -R "$REPO/req_compile" "$STAGE/req_compile"
cp -R "$PY_SITE/packaging" "$STAGE/packaging"
cp -R "$PY_SITE/overrides" "$STAGE/overrides"
cp -R "$HERE/shims/." "$STAGE/"
# With a host interpreter of the embedded version the bundle holds bytecode,
# which spares every call the compilation of the sources it imports.
BUNDLE_PYTHON="${BUNDLE_PYTHON:-python3}"
PYC=""
if "$BUNDLE_PYTHON" -c "import sys; sys.exit('%d.%d' % sys.version_info[:2] != '$PY_VERSION')"; then
    PYC="--pyc"
else
    echo "note: $BUNDLE_PYTHON is not Python $PY_VERSION; bundling source instead of bytecode"
fi
"$BUNDLE_PYTHON" "$HERE/bundle.py" --out "$BUILD/bundle.bin" --stdlib "$PY_LIB" --root "$STAGE" $PYC
cp "$HERE/bootstrap.py" "$BUILD/bootstrap.py"

# The `encodings` modules the interpreter imports while starting, frozen in;
# the bytecode format requires a host interpreter of the embedded version.
if [ -z "$PYC" ]; then
    echo "error: freezing \`encodings\` needs a host Python $PY_VERSION; set BUNDLE_PYTHON" >&2
    exit 1
fi
"$BUNDLE_PYTHON" "$HERE/freeze_encodings.py" "$PY_LIB" "$BUILD/frozen_encodings.c"

# 3. Compile the host pieces and link a reactor module with no imports.
echo "linking"
"$CC" "${CFLAGS[@]}" -c "$HERE/wasi_stubs.c" -o "$BUILD/wasi_stubs.o"
"$CC" "${CFLAGS[@]}" -c "$HERE/shim.c" -o "$BUILD/shim.o"
"$CC" "${CFLAGS[@]}" -c "$BUILD/frozen_encodings.c" -o "$BUILD/frozen_encodings.o"
(cd "$BUILD" && "$CC" --target=wasm32-wasi -c "$HERE/embed.S" -o "$BUILD/embed.o")
# No `-O2` at link time: with it, wasm-ld emits a `_PyEval_EvalFrameDefault`
# that Bazel's runtime cannot compile into one JVM method and interprets instead,
# which costs the solver an order of magnitude (see README.md, "Where the time
# goes"). `--strip-all` also drops the name section; a build meant for
# profiling sets LINK_FLAGS to "" to keep function names.
LINK_FLAGS="${LINK_FLAGS--Wl,--strip-all}"
# shellcheck disable=SC2086
"$CC" --target=wasm32-wasi -mexec-model=reactor $LINK_FLAGS \
    -o "$OUT" \
    "$BUILD/shim.o" "$BUILD/wasi_stubs.o" "$BUILD/embed.o" "$BUILD/frozen_encodings.o" \
    "$LIBPYTHON" "$BUILD/extra/libextra.a" \
    -ldl -lwasi-emulated-signal -lwasi-emulated-getpid -lwasi-emulated-process-clocks -lm \
    -Wl,-z,stack-size=1048576 \
    -Wl,--initial-memory=67108864
# 4. Optionally pre-initialize: run the interpreter start and the imports now,
#    snapshot the memory into the module, and every call starts from there.
if [ -n "${WIZER:-}" ]; then
    echo "pre-initializing with wizer"
    "$WIZER" --init-func wizer.initialize --wasm-bulk-memory true -o "$OUT.wizer" "$OUT"
    # The snapshot is one segment per run of non-zero bytes, far more than
    # runtimes accept; merge them.
    python3 "$HERE/merge_segments.py" "$OUT.wizer" "$OUT"
    rm -f "$OUT.wizer"
fi

ls -la "$OUT"
# The module must import nothing: Bazel instantiates it with no imports at all.
# `run_local.py` and the example exercise that for real; this is the early check.
if command -v wasm-tools >/dev/null 2>&1; then
    if wasm-tools print "$OUT" | grep -qE '^\s*\(import'; then
        echo "error: the module still imports functions:" >&2
        wasm-tools print "$OUT" | grep -E '^\s*\(import' | sed -E 's/ \((func|memory|table|global).*//' | sort | uniq -c >&2
        exit 1
    fi
    echo "imports: none"
else
    echo "note: wasm-tools not found; the import check is left to the smoke tests"
fi
