"""Re-export the parse extension under a different name so we don't
create a cirular dep tree during test."""

load("//extensions:python.bzl", _requirements = "requirements")

requirements = _requirements
