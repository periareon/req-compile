"""Stand-in for `toml`: pyproject metadata is never read inside the WebAssembly solver."""


def load(*args, **kwargs):
    raise RuntimeError(
        "pyproject.toml parsing is not available in the WebAssembly solver"
    )


def loads(*args, **kwargs):
    raise RuntimeError(
        "pyproject.toml parsing is not available in the WebAssembly solver"
    )
