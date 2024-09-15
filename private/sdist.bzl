"""Requirements for extracting and building source dists."""

load(":reqs_repo.bzl", "create_spoke_repos", "parse_requirements_locks")

def _sdist_deps_module_impl(module_ctx):
    attrs = struct(
        requirements_lock = Label("//private:sdist_requirements.txt"),
        requirements_locks = None,
    )
    platform_packages = parse_requirements_locks(
        hub_name = "req_compile_sdist_compiler",
        ctx = module_ctx,
        attrs = attrs,
        annotations = {},
    )
    for data in platform_packages.values():
        create_spoke_repos("req_compile_sdist_compiler", data.packages, interpreter = None)

    return module_ctx.extension_metadata(
        root_module_direct_deps = "all",
        root_module_direct_dev_deps = [],
        reproducible = True,
    )

sdist_deps = module_extension(
    doc = "Load all cross-platform wheels required to build source distributions.",
    implementation = _sdist_deps_module_impl,
)
