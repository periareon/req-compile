#!/bin/bash
# Build `req_compile_solver.wasm` from pinned inputs.
#
# Everything the module is made of is named here by version and hash: the
# wasi-sdk, the CPython release, Wizer, and the two Python packages the solver
# depends on. They are downloaded and verified into a work directory, CPython
# is cross-compiled by `build_cpython.sh` (with the trampoline interpreter) and
# the module is linked and pre-initialized by `build.sh`. The same inputs give
# the same module; CI runs this on every change and the release attaches its
# output.
#
# Host requirements: bash, curl, tar, xz, make, a C compiler (CPython builds a
# native interpreter first and uses it to cross-compile) and a `python3` for
# CPython's own build driver. No particular Python version: the bytecode in
# the module is produced by the interpreter CPython builds for itself.
#
# Optional environment:
#   WORK  downloads and intermediate builds, reused across runs
#         (default: wasm/build/work)
#   OUT   the module (default: wasm/build/req_compile_solver.wasm)
#
# Usage: wasm/build_solver.sh
set -euo pipefail

# ---- Pinned inputs ---------------------------------------------------------

CPYTHON_VERSION=3.14.8
CPYTHON_URL="https://www.python.org/ftp/python/${CPYTHON_VERSION}/Python-${CPYTHON_VERSION}.tar.xz"
CPYTHON_SHA256=c2215904f02b175596dc49351585104f4bc20341e1c47378b26a2c274360ce73

WASI_SDK_VERSION=24.0
WASI_SDK_URL_BASE="https://github.com/WebAssembly/wasi-sdk/releases/download/wasi-sdk-${WASI_SDK_VERSION%%.*}"

WIZER_VERSION=11.0.3
WIZER_URL_BASE="https://github.com/bytecodealliance/wizer/releases/download/v${WIZER_VERSION}"

PACKAGING_URL="https://files.pythonhosted.org/packages/63/34/ba1c580383c9eada3711951fef0795c80b829a078d72188184bcab9dd527/packaging-26.3-py3-none-any.whl"
PACKAGING_SHA256=d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c
OVERRIDES_URL="https://files.pythonhosted.org/packages/2c/ab/fc8290c6a4c722e5514d80f62b2dc4c4df1a68a41d1364e625c35990fcf3/overrides-7.7.0-py3-none-any.whl"
OVERRIDES_SHA256=c7ed9d062f78b8e4c1a7b70bd8796b35ead4d9f510227ef9c5dc7626c60d7e49

# The tool archives per host. wasi-sdk and Wizer name the architectures
# differently.
case "$(uname -s)-$(uname -m)" in
    Darwin-arm64)
        WASI_SDK_HOST=arm64-macos
        WASI_SDK_SHA256=aeae999396d5f5caa5ce419f52e83c35869d5fd21d40af80acba2c80f51b0b3a
        WIZER_HOST=aarch64-macos
        WIZER_SHA256=7c54896b456b6ca024af6005ebc5538282dee7cd9f0c9c1155855d29b9c461b1
        ;;
    Darwin-x86_64)
        WASI_SDK_HOST=x86_64-macos
        WASI_SDK_SHA256=4bfc274ae8b68c771dd93e32ad4bd695336ca46b585beb3b1260e5602dbc11a2
        WIZER_HOST=x86_64-macos
        WIZER_SHA256=325bcd4758e9509dd81849d7f4ab8cf69cbe084795e138a996c70f471b6f8b83
        ;;
    Linux-x86_64)
        WASI_SDK_HOST=x86_64-linux
        WASI_SDK_SHA256=c6c38aab56e5de88adf6c1ebc9c3ae8da72f88ec2b656fb024eda8d4167a0bc5
        WIZER_HOST=x86_64-linux
        WIZER_SHA256=36016e7f846f38ad09f22eb4bafb99068f038c431eb9613ddf59e31ad8a21414
        ;;
    Linux-aarch64)
        WASI_SDK_HOST=arm64-linux
        WASI_SDK_SHA256=ae6c1417ea161e54bc54c0a168976af57a0c6e53078857886057a71a0d928646
        WIZER_HOST=aarch64-linux
        WIZER_SHA256=73bffcbaf736ef24109a48cac431d070c43cb2ee8a14a840576f7aec0133d8d6
        ;;
    *)
        echo "error: no pinned wasi-sdk and Wizer for $(uname -s) $(uname -m)" >&2
        exit 1
        ;;
esac

# ---- Helpers ---------------------------------------------------------------

HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="${WORK:-$HERE/build/work}"
OUT="${OUT:-$HERE/build/req_compile_solver.wasm}"
mkdir -p "$WORK/downloads" "$(dirname "$OUT")"

sha256() {
    python3 -I -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$1"
}

# fetch URL SHA256 -> the verified file under downloads/, downloading it once.
fetch() {
    local url="$1" expected="$2" file="$WORK/downloads/$(basename "$1")"
    if [ ! -f "$file" ]; then
        echo "downloading $(basename "$url")" >&2
        curl -fsSL --retry 3 -o "$file.part" "$url"
        mv "$file.part" "$file"
    fi
    local actual
    actual="$(sha256 "$file")"
    if [ "$actual" != "$expected" ]; then
        echo "error: $(basename "$url") has sha256 $actual, expected $expected" >&2
        rm -f "$file"
        exit 1
    fi
    echo "$file"
}

# ---- 1. The toolchain: wasi-sdk and Wizer ----------------------------------

WASI_SDK="$WORK/wasi-sdk-${WASI_SDK_VERSION}-${WASI_SDK_HOST}"
if [ ! -x "$WASI_SDK/bin/clang" ]; then
    archive="$(fetch "${WASI_SDK_URL_BASE}/wasi-sdk-${WASI_SDK_VERSION}-${WASI_SDK_HOST}.tar.gz" "$WASI_SDK_SHA256")"
    rm -rf "$WASI_SDK" && tar -xzf "$archive" -C "$WORK"
fi

WIZER="$WORK/wizer-v${WIZER_VERSION}-${WIZER_HOST}/wizer"
if [ ! -x "$WIZER" ]; then
    archive="$(fetch "${WIZER_URL_BASE}/wizer-v${WIZER_VERSION}-${WIZER_HOST}.tar.xz" "$WIZER_SHA256")"
    rm -rf "$(dirname "$WIZER")" && tar -xJf "$archive" -C "$WORK"
fi

# ---- 2. CPython, cross-compiled for wasm32-wasi ----------------------------

CPYTHON_SRC="$WORK/Python-${CPYTHON_VERSION}"
if [ ! -f "$CPYTHON_SRC/Include/patchlevel.h" ]; then
    archive="$(fetch "$CPYTHON_URL" "$CPYTHON_SHA256")"
    rm -rf "$CPYTHON_SRC" && tar -xJf "$archive" -C "$WORK"
fi

# Rebuild when the build script or the patch changed since the last build.
PY_BUILD="$CPYTHON_SRC/cross-build/wasm32-wasip1"
STAMP="$CPYTHON_SRC/.req_compile_build"
WANT="$(cat "$HERE/build_cpython.sh" "$HERE/patches/"*.patch | sha256 /dev/stdin)"
if [ ! -f "$PY_BUILD/libpython${CPYTHON_VERSION%.*}.a" ] || [ "$(cat "$STAMP" 2>/dev/null)" != "$WANT" ]; then
    echo "building CPython ${CPYTHON_VERSION} for wasm32-wasi" >&2
    CLEAN=1 TRAMPOLINE=1 WASI_SDK="$WASI_SDK" CPYTHON_SRC="$CPYTHON_SRC" bash "$HERE/build_cpython.sh" >&2
    echo "$WANT" > "$STAMP"
fi

# The native interpreter CPython built for itself along the way is the host
# Python of the module's version: it produces the bytecode bundle and the
# frozen `encodings` table.
BUNDLE_PYTHON=""
for candidate in "$CPYTHON_SRC"/cross-build/*/python.exe "$CPYTHON_SRC"/cross-build/*/python; do
    case "$candidate" in */wasm32-*) continue ;; esac
    if [ -x "$candidate" ]; then
        BUNDLE_PYTHON="$candidate"
        break
    fi
done
if [ -z "$BUNDLE_PYTHON" ]; then
    echo "error: CPython's build interpreter not found under $CPYTHON_SRC/cross-build" >&2
    exit 1
fi

# ---- 3. The Python dependencies --------------------------------------------

PY_SITE="$WORK/site"
if [ ! -d "$PY_SITE/packaging" ] || [ ! -d "$PY_SITE/overrides" ]; then
    rm -rf "$PY_SITE" && mkdir -p "$PY_SITE"
    for wheel in "$(fetch "$PACKAGING_URL" "$PACKAGING_SHA256")" "$(fetch "$OVERRIDES_URL" "$OVERRIDES_SHA256")"; do
        python3 -I -m zipfile -e "$wheel" "$PY_SITE"
    done
fi

# ---- 4. The module ---------------------------------------------------------

WASI_SDK="$WASI_SDK" \
PY_BUILD="$PY_BUILD" \
PY_SRC="$CPYTHON_SRC" \
PY_LIB="$CPYTHON_SRC/Lib" \
PY_SITE="$PY_SITE" \
BUNDLE_PYTHON="$BUNDLE_PYTHON" \
WIZER="$WIZER" \
BUILD_DIR="$WORK/module" \
OUT="$OUT" \
bash "$HERE/build.sh" >&2

echo "$(sha256 "$OUT")  $OUT"
