"""Bazel utilities for req-compile rules."""

def sanitize_package_name(name):
    """Sanitize a python package name to a consistent and safe name for Bazel

    Args:
        name (str): The name of a python package

    Returns:
        str: A sanitized python package.
    """
    return name.replace("-", "_").replace(".", "_").lower()

def sanitize_version(version):
    """Sanitize a python package version into a string safe for repository names.

    Args:
        version (str): A package version.

    Returns:
        str: The sanitized version.
    """
    return "".join([
        char if char.isalnum() else "_"
        for char in version.elems()
    ])

def short_hash(text):
    """Produce a short, stable hexadecimal digest of a string.

    Args:
        text (str): The text to hash.

    Returns:
        str: Eight hexadecimal characters.
    """
    digest = "%x" % (hash(text) & 0xffffffff)
    return "0" * (8 - len(digest)) + digest

def whl_repo_name(package, version, identity, annotations = None):
    """Compute the name of the `whl_repository` holding a particular wheel.

    Wheels are shared between every hub that uses them, so the name only
    depends on the wheel itself and on anything that changes its contents.

    Args:
        package (str): The python package name.
        version (str): The package version.
        identity (str): Something identifying the exact distribution, preferably
            its sha256 digest, otherwise its URL or label.
        annotations (str): Serialized annotations applied to the wheel, if any.
            Annotations change the contents of the repository, so annotated
            wheels get a distinct repository.

    Returns:
        str: A Bazel repository name.
    """
    if len(identity) == 64 and identity.lower() == identity and identity.isalnum():
        suffix = identity[:8]
    else:
        suffix = short_hash(identity)

    name = "{}_{}_{}".format(
        sanitize_package_name(package),
        sanitize_version(version),
        suffix,
    )
    if annotations and annotations not in ("{}", "null", '""'):
        name += "_" + short_hash(annotations)
    return name

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
