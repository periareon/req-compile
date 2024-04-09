"""Test dependencies for `pip_parse` compatibility tests"""

load(
    "@req_compile_test_pip_parse_compat_multi_plat//:requirements.bzl",
    pip_parse_compat_multi_plat_repositories = "install_deps",
)
load(
    "@req_compile_test_pip_parse_compat_single_plat//:requirements.bzl",
    pip_parse_compat_single_plat_repositories = "install_deps",
)

def pip_parse_compat_test_deps_install():
    pip_parse_compat_multi_plat_repositories()
    pip_parse_compat_single_plat_repositories()
