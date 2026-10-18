"""Stand-in for `requests` so `req_compile.repos.pypi` imports without network support.

Inside the WebAssembly solver nothing downloads: Bazel fetches every page and
file. Only the names `pypi.py` touches at import time and in constructors exist.
"""


class Session:
    def get(self, *args, **kwargs):
        raise RuntimeError(
            "the WebAssembly solver cannot download; Bazel fetches for it"
        )

    def close(self):
        pass


def get(*args, **kwargs):
    raise RuntimeError("the WebAssembly solver cannot download; Bazel fetches for it")
