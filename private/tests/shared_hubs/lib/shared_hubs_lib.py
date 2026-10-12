"""A library of a dependent module using its own requirements hub."""

import click  # pylint: disable=import-error
import requests  # pylint: disable=import-error


def locations() -> dict[str, str]:
    """The files the packages of this module were imported from."""
    return {
        "click": click.__file__,
        "requests": requests.__file__,
    }
