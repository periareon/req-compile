"""A `ThreadPool` that runs its work inline.

`req_compile.repos.source` imports it to scan source trees in parallel, which
the WebAssembly solver never does, and the WASI build of CPython has neither
threads nor the `multiprocessing` package.
"""


class ThreadPool:
    def __init__(self, *_args, **_kwargs):
        pass

    def map(self, func, iterable, chunksize=None):
        del chunksize
        return [func(item) for item in iterable]

    def imap(self, func, iterable, chunksize=1):
        del chunksize
        return (func(item) for item in iterable)

    imap_unordered = imap

    def apply(self, func, args=(), kwds=None):
        return func(*args, **(kwds or {}))

    def close(self):
        pass

    def terminate(self):
        pass

    def join(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass
