"""The solver module that belongs to this release of `rules_req_compile`.

`.github/workflows/release_prep.sh` builds `req_compile_solver.wasm` for each
release, attaches it to the GitHub release and fills in `SOLVER_SHA256` below in
the copy of this file that goes into the module archive. The `requirements`
extension downloads the module from here the first time a hub resolves, through
Bazel's repository cache. A source checkout carries no hash and says so;
`wasm/build_solver.sh` builds a module to name with the `solver` attribute.
"""

load("//:version.bzl", "VERSION")

SOLVER_URL = "https://github.com/periareon/req-compile/releases/download/{}/req_compile_solver.wasm".format(VERSION)

# Filled in by release_prep.sh; empty in a source checkout.
SOLVER_SHA256 = ""
