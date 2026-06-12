"""Bazel utilities for req-compile rules."""

def sanitize_package_name(name):
    """Sanitize a python package name to a consistent and safe name for Bazel

    Args:
        name (str): The name of a python package

    Returns:
        str: A sanitized python package.
    """
    return name.replace("-", "_").replace(".", "_").lower()

def whl_repo_name(spoke_prefix, package):
    """Compute the name name for a `whl_repository`

    Args:
        spoke_prefix (str): The name of a `py_requirements_repository` like rule plus a platform suffix.
        package (str): The package name for the wheel.

    Returns:
        str: A Bazel repository name.
    """
    return spoke_prefix + "__" + sanitize_package_name(package)

_EXECUTE_FAIL_MESSAGE = """\
Process exited with code '{code}'
# ARGV ########################################################################
{argv}

# STDOUT ######################################################################
{stdout}

# STDERR ######################################################################
{stderr}
"""

def execute(repository_ctx, args, **kwargs):
    """Run a subprocess and error if it fails

    Args:
        repository_ctx (repository_ctx): The rule's context object
        args (list): The argv of the command to run.
        **kwargs (dict): Additional keyword arguments.

    Returns:
        struct: The results of `repository_ctx.execute`.
    """
    result = repository_ctx.execute(args, **kwargs)

    if result.return_code:
        fail(_EXECUTE_FAIL_MESSAGE.format(
            code = result.return_code,
            argv = args,
            stdout = result.stdout,
            stderr = result.stderr,
        ))

    return result

def parse_artifact_name(urls):
    """Parse the artifact name from a pypi url.

    Args:
        urls (list): A list of urls

    Returns:
        Optional[str]: The name if it was correctly parsed, otherwise None.
    """
    name = None
    for url in urls:
        link, _, _ = url.partition("#sha256=")
        _, _, name = link.rpartition("/")
        if name:
            break
    return name
