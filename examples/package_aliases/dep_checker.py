import sys


def main() -> None:
    # Don't let the interpreter's built-in packages pollute the import.
    for path in list(sys.path):
        if "rules_python" in path and "site-packages" in path:
            sys.path.remove(path)

    import setuptools  # pylint: disable=import-outside-toplevel

    assert (
        "site-packages" not in setuptools.__file__
    ), f"Expected the overridden package, imported {setuptools.__file__} instead."


if __name__ == "__main__":
    main()
