"""Requirements for extracting and building source dists."""

load(":lockfile.bzl", "parse_lockfile")
load(":whl_repo.bzl", "whl_repository")

SDIST_COMPILER_HUB = "req_compile_sdist_compiler"

def _sdist_deps_module_impl(module_ctx):
    lockfile = Label("//private:sdist_requirements.txt")
    packages = parse_lockfile(
        content = module_ctx.read(module_ctx.path(lockfile)),
        annotations = {},
        lockfile = lockfile,
    )

    # These repositories are referenced by name from `whl_repository`, so
    # they intentionally do not use the content based naming of hub wheels.
    for name, data in packages.items():
        whl_repository(
            name = "{}__{}".format(SDIST_COMPILER_HUB, name),
            package = name,
            sha256 = data["sha256"],
            urls = [data["url"]] if data["url"] else None,
            version = data["version"],
            whl = data["whl"],
            # Avoid a circular dependency when creating the repos for the source dist
            # dependencies. We don't need these for non-source dist repos anyway.
            sdist_deps_repos = [],
        )

    return module_ctx.extension_metadata(
        root_module_direct_deps = "all",
        root_module_direct_dev_deps = [],
        reproducible = True,
    )

sdist_deps = module_extension(
    doc = "Load all cross-platform wheels required to build source distributions.",
    implementation = _sdist_deps_module_impl,
)
