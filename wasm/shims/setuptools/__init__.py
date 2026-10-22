"""Stand-in for `setuptools`: `setup.py` is never executed inside the WebAssembly solver."""


def setup(**_kwargs):
    raise RuntimeError("setup.py execution is not available in the WebAssembly solver")


def find_packages(*_args, **_kwargs):
    return []


def find_namespace_packages(*_args, **_kwargs):
    return []
