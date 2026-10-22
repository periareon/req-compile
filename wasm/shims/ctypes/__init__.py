"""Stand-in for `ctypes`: nothing can be loaded dynamically inside the WebAssembly solver.

`req_compile.utils.get_glibc_version` treats a failing `CDLL(None)` as "not glibc",
which is the right answer for the interpreter hosting the solver. Targets are
always described explicitly, so the host's own platform is never used.
"""


class CDLL:
    def __init__(self, *_args, **_kwargs):
        raise TypeError("dynamic loading is not available in the WebAssembly solver")
