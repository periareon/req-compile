"""The functions `req_compile_solver.wasm` exports.

`//wasm:req_compile_solver` is a `py_wasm_module` of rules_venv whose `entry`
is this module: each export takes the input of a call as `bytes` and returns
the output and the return code of the call. Bazel calls one function, `solve`;
the operation (`ping`, `ingest` or `solve`) is the `op` of its JSON payload,
which `entry.main` dispatches on.
"""

from typing import Tuple

from req_compile.wasm import entry


def solve(data: bytes) -> Tuple[bytes, int]:
    """One call of the module: the output and the return code."""
    return entry.main(data)
