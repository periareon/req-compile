#!/usr/bin/env bash
# Build the rules_req_compile release assets and emit release notes.
# Invoked by bazel-contrib/.github/.github/workflows/release_ruleset.yaml
# at the hardcoded path `.github/workflows/release_prep.sh`.
#
# Args:
#   $1: tag name (e.g. 1.2.0). Must match VERSION in version.bzl and the
#       module version in MODULE.bazel.
#
# Side effects:
#   Writes the following to the current directory. These paths must match
#   the `release_files` globs in release.yaml.
#     rules_req_compile-${TAG}.tar.gz   The Bazel module source archive.
#     dist/*.whl, dist/*.tar.gz         The Python wheel and sdist that are
#                                       published to PyPI.
#
# Output:
#   Release notes to stdout. The release_ruleset workflow redirects
#   stdout into release_notes.txt for the GitHub release body. All
#   other noise (tar, pip, version checks) goes to stderr.

set -euo pipefail

# Redirect all stdout to stderr; keep fd 3 for the final release-notes write.
exec 3>&1 1>&2

TAG="${1:?tag_name required}"
WORKSPACE="${GITHUB_WORKSPACE:-$(pwd)}"

# Validate the tag matches version.bzl and MODULE.bazel. release.yaml's
# `validation` job also guards the tag, but checking again here means a
# manual invocation of this script can't drift, and a release commit that
# bumped only one of the two files is rejected before anything is published.
ON_DISK_VERSION="$(grep 'VERSION =' "${WORKSPACE}/version.bzl" | sed 's/VERSION = "//' | sed 's/"//')"
if [[ "${ON_DISK_VERSION}" != "${TAG}" ]]; then
    echo "ERROR: tag ${TAG} does not match version.bzl VERSION=${ON_DISK_VERSION}"
    exit 1
fi
MODULE_VERSION="$(sed -n -E 's/^[[:space:]]*version = "([^"]+)",?$/\1/p' "${WORKSPACE}/MODULE.bazel" | head -n 1)"
if [[ "${MODULE_VERSION}" != "${TAG}" ]]; then
    echo "ERROR: tag ${TAG} does not match MODULE.bazel version=${MODULE_VERSION}"
    exit 1
fi

SCRATCH="$(mktemp -d)"
trap 'rm -rf "${SCRATCH}"' EXIT

# Build the Bazel module source archive. Exclude .git (history isn't
# needed by consumers), .github (release infrastructure isn't part of
# the ruleset), the Python packaging outputs, and anything Bazel may
# have left in the workspace. The on-disk filename matches the URL in
# `.bcr/source.template.json` — the SLSA attestation subject must
# equal the published asset name.
#
# Excludes are anchored to the workspace root (`./`) so that tracked
# files such as `3rdparty/bazel-requirements.in` are not swept up by
# the `bazel-*` convenience symlink pattern.
#
# Stage to a temp path *outside* the workspace before moving into cwd:
# writing the archive into the same directory tar is reading from
# updates that directory's mtime mid-read, which GNU tar surfaces as
# `tar: .: file changed as we read it` and aborts with non-zero.
ARCHIVE="rules_req_compile-${TAG}.tar.gz"
tar -czf "${SCRATCH}/${ARCHIVE}" \
    --exclude="./.git" \
    --exclude="./.github" \
    --exclude="./scripts" \
    --exclude="./dist" \
    --exclude="./build" \
    --exclude="./*.egg-info" \
    --exclude="./MODULE.bazel.lock" \
    --exclude="./bazel-*" \
    -C "${WORKSPACE}" .
mv "${SCRATCH}/${ARCHIVE}" "${ARCHIVE}"

# Build the Python wheel and sdist into `dist/`. Building these here
# (rather than in a separate job) means the same bytes that are attested
# and attached to the GitHub release are the ones later uploaded to PyPI
# by release.yaml's `pypi-publish` job.
#
# The wheel is the `py_wheel_library` target built by Bazel, so it is the
# exact artifact the rest of the repository tests against. `python -m build`
# runs in an isolated environment, so the host Python only needs `venv`, and
# is still used for the source distribution.
rm -rf dist
mkdir dist
(cd "${WORKSPACE}" && bazel build //req_compile:req_compile.whl)
cp "${WORKSPACE}/$(cd "${WORKSPACE}" && bazel cquery --output=files //req_compile:req_compile.whl)" dist/
python3 -m venv "${SCRATCH}/venv"
"${SCRATCH}/venv/bin/python" -m pip install --quiet --upgrade pip build
"${SCRATCH}/venv/bin/python" -m build --sdist --outdir dist "${WORKSPACE}"

# Render release notes by substituting {version} into the template.
# release_notes.template lives in `.github/`.
sed "s#{version}#${TAG}#g" \
    "${WORKSPACE}/.github/release_notes.template" > "${SCRATCH}/release_notes.txt"

# Emit the rendered notes on the original stdout (fd 3) — that's the
# only thing the reusable workflow captures into release_notes.txt.
cat "${SCRATCH}/release_notes.txt" >&3
