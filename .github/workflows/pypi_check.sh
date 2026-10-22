#!/usr/bin/env bash
# Decide whether a release carries Python changes that PyPI does not have yet.
#
# Compares the inputs of the Python distributions (the `req_compile` package
# without `req_compile/private`, the packaging files, README.rst, LICENSE.txt
# and requirements.in) between the commit being released and the commit of
# the newest release on PyPI, found by its tag. version.bzl and CHANGELOG.rst
# are not inputs: a release that only bumps the version or adds notes for the
# Bazel side publishes nothing new to PyPI.
#
# Args:
#   $1: commit to release (default HEAD).
#
# Output:
#   `publish=true|false` and `reason=...` to $GITHUB_OUTPUT when set, and to
#   stdout; the reason also goes to $GITHUB_STEP_SUMMARY when set.
#   Exits non-zero when PyPI cannot be consulted, so that nothing is decided
#   on a guess.

set -euo pipefail

COMMIT="${1:-HEAD}"
PROJECT="${PYPI_PROJECT:-req-compile}"
PYPI_JSON_URL="${PYPI_JSON_URL:-https://pypi.org/pypi/${PROJECT}/json}"

# Everything setup.py and MANIFEST.in put in the sdist and `py_wheel_library`
# in the wheel, less the version and the changelog. Bazel's own files under
# the package are not in either; a BUILD change that adds a file to the wheel
# adds that file too, which is seen.
INPUTS=(
    "req_compile"
    ":(exclude)req_compile/private"
    ":(exclude,glob)req_compile/**/BUILD.bazel"
    ":(exclude,glob)req_compile/**/*.bzl"
    "setup.py"
    "setup.cfg"
    "pyproject.toml"
    "MANIFEST.in"
    "requirements.in"
    "README.rst"
    "LICENSE.txt"
)

emit() {
    local publish="$1" reason="$2"
    echo "publish=${publish}"
    echo "reason=${reason}"
    if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
        {
            echo "publish=${publish}"
            echo "reason=${reason}"
        } >> "${GITHUB_OUTPUT}"
    fi
    if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
        echo "PyPI: ${reason}" >> "${GITHUB_STEP_SUMMARY}"
    fi
}

git fetch --tags --quiet origin 2>/dev/null || true

# The newest release on PyPI by upload time, pre-releases included, and the
# tag it was released from: the tag whose PEP 440 normalization is that
# version (`1.6.5-rc2` publishes as `1.6.5rc2`).
python3 -m pip install --quiet --disable-pip-version-check packaging >&2
mapfile -t TAGS < <(git tag --list)
if ! PYPI_JSON="$(curl --silent --show-error --fail --location "${PYPI_JSON_URL}")"; then
    echo "ERROR: could not read ${PYPI_JSON_URL}; not deciding whether to publish without it" >&2
    exit 1
fi
PYPI_LATEST="$(
    python3 -c '
import json, sys
from packaging.version import InvalidVersion, Version

releases = json.load(sys.stdin)["releases"]
by_upload = sorted(
    (max(f["upload_time"] for f in files), version)
    for version, files in releases.items()
    if files and not all(f.get("yanked") for f in files)
)
latest = Version(by_upload[-1][1])
tags = sys.argv[1:]
for tag in tags:
    try:
        if Version(tag) == latest:
            print(latest, tag)
            break
    except InvalidVersion:
        continue
else:
    print(latest, "")
' "${TAGS[@]}" <<< "${PYPI_JSON}"
)"
LATEST_VERSION="${PYPI_LATEST%% *}"
LATEST_TAG="${PYPI_LATEST#* }"

if [[ -z "${LATEST_TAG}" ]]; then
    emit true "${LATEST_VERSION} is the newest release on PyPI and no tag of this repository matches it, so the distributions are published."
    exit 0
fi

if git diff --quiet "${LATEST_TAG}" "${COMMIT}" -- "${INPUTS[@]}"; then
    emit false "the Python distributions have the same inputs as ${LATEST_VERSION} (tag ${LATEST_TAG}), the newest release on PyPI, so they are not published."
else
    CHANGED="$(git diff --name-only "${LATEST_TAG}" "${COMMIT}" -- "${INPUTS[@]}" | tr '\n' ' ')"
    emit true "the Python distributions differ from ${LATEST_VERSION} (tag ${LATEST_TAG}), the newest release on PyPI, so they are published. Changed: ${CHANGED}"
fi
