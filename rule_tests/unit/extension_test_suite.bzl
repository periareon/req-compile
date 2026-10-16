"""Starlark unit tests for the planning done by the `requirements` extension."""

# buildifier: disable=bzl-visibility
load("@bazel_skylib//lib:unittest.bzl", "asserts", "unittest")

# buildifier: disable=bzl-visibility
load("//req_compile/private:annotation_utils.bzl", "ROOT_MODULE", "deserialize_package_annotation", "record_annotation")

# buildifier: disable=bzl-visibility
load("//req_compile/private:reqs_repo.bzl", "is_sdist", "merge_wheel")

# buildifier: disable=bzl-visibility
load("//req_compile/private:whl_repo.bzl", "hub_deps", "render_deps")

_NO_ANNOTATIONS = deserialize_package_annotation("{}")

def _deps_single_lock_test_impl(ctx):
    env = unittest.begin(ctx)
    hub_data = {
        "default_lock": None,
        "locks": {"linux": {"config_setting": None, "deps": ["six", "Click"]}},
    }
    deps = hub_deps("hub", hub_data, _NO_ANNOTATIONS)
    asserts.equals(env, {None: ["@hub//click", "@hub//six"]}, deps.branches)
    asserts.false(env, deps.empty)
    asserts.equals(
        env,
        json.encode_indent(["@hub//click", "@hub//six"], indent = "    "),
        render_deps([], deps),
    )
    return unittest.end(env)

deps_single_lock_test = unittest.make(_deps_single_lock_test_impl)

def _deps_default_lock_test_impl(ctx):
    env = unittest.begin(ctx)
    hub_data = {
        "default_lock": "linux",
        "locks": {
            "linux": {"config_setting": "@hub//:linux", "deps": ["six"]},
            "windows": {"config_setting": "@hub//:windows", "deps": ["six", "colorama"]},
        },
    }
    deps = hub_deps("hub", hub_data, _NO_ANNOTATIONS)
    asserts.equals(env, {
        "@hub//:linux": ["@hub//six"],
        "@hub//:windows": ["@hub//colorama", "@hub//six"],
    }, deps.branches)

    # The fallback lock's dependencies apply when no lock matches.
    asserts.equals(env, ["@hub//six"], deps.default)

    rendered = render_deps(["@extra//:dep"], deps)
    asserts.true(env, rendered.startswith('["@extra//:dep"] + select({'), rendered)
    asserts.true(env, '"//conditions:default": ["@hub//six"],' in rendered, rendered)
    return unittest.end(env)

deps_default_lock_test = unittest.make(_deps_default_lock_test_impl)

def _deps_no_default_lock_test_impl(ctx):
    env = unittest.begin(ctx)
    hub_data = {
        "default_lock": "macos",
        "locks": {
            "linux": {"config_setting": "@hub//:linux", "deps": []},
            "windows": {"config_setting": "@hub//:windows", "deps": ["colorama"]},
        },
    }
    deps = hub_deps("hub", hub_data, _NO_ANNOTATIONS)

    # The wheel is not part of the fallback lock, so the hub never falls back to it.
    asserts.equals(env, None, deps.default)
    asserts.false(env, "//conditions:default" in render_deps([], deps), render_deps([], deps))

    # A hub whose locks resolved nothing has no library of its own.
    hub_data["locks"]["windows"]["deps"] = []
    asserts.true(env, hub_deps("hub", hub_data, _NO_ANNOTATIONS).empty)
    return unittest.end(env)

deps_no_default_lock_test = unittest.make(_deps_no_default_lock_test_impl)

def _wheel(**kwargs):
    attrs = {
        "annotations": "{}",
        "hubs": {"first": {}},
        "interpreter": None,
        "package": "click",
        "sha256": "a" * 64,
        "urls": ["https://pypi.org/click-8.1.7-py3-none-any.whl#sha256=" + "a" * 64],
        "version": "8.1.7",
        "whl": None,
    }
    attrs.update(kwargs)
    return attrs

def _merge_mirrors_test_impl(ctx):
    env = unittest.begin(ctx)
    mirror = "https://mirror.example.com/click-8.1.7-py3-none-any.whl"
    merged = merge_wheel("click_8_1_7_aaaaaaaa", _wheel(), _wheel(urls = [mirror]), "second")

    # The same bytes from two places are one repository with both download locations.
    asserts.equals(env, [_wheel()["urls"][0], mirror], merged["urls"])
    asserts.equals(env, "a" * 64, merged["sha256"])
    return unittest.end(env)

merge_mirrors_test = unittest.make(_merge_mirrors_test_impl)

def _merge_interpreters_test_impl(ctx):
    env = unittest.begin(ctx)

    # Ordinary wheels are shared regardless of the interpreters of the hubs.
    asserts.false(env, is_sdist(_wheel()))
    merged = merge_wheel(
        "click_8_1_7_aaaaaaaa",
        _wheel(interpreter = Label("//:python_a")),
        _wheel(interpreter = Label("//:python_b")),
        "second",
    )
    asserts.equals(env, None, merged["interpreter"])

    sdist = _wheel(urls = ["https://pypi.org/click-8.1.7.tar.gz"], interpreter = None)
    asserts.true(env, is_sdist(sdist))
    merged = merge_wheel("click_8_1_7_aaaaaaaa", sdist, _wheel(urls = sdist["urls"], interpreter = Label("//:python_b")), "second")
    asserts.equals(env, Label("//:python_b"), merged["interpreter"])
    return unittest.end(env)

merge_interpreters_test = unittest.make(_merge_interpreters_test_impl)

def _annotation_ownership_test_impl(ctx):
    env = unittest.begin(ctx)
    annotations = {}
    owners = {}

    # The root declares A, a dependency repeats A, another dependency declares B.
    record_annotation(annotations, owners, "numpy", "A", "root", True)
    record_annotation(annotations, owners, "numpy", "A", "dep_one", False)
    asserts.equals(env, ROOT_MODULE, owners["numpy"])
    record_annotation(annotations, owners, "numpy", "B", "dep_two", False)
    asserts.equals(env, "A", annotations["numpy"])
    asserts.equals(env, ROOT_MODULE, owners["numpy"])

    # A dependency declares first, the root then decides differently.
    record_annotation(annotations, owners, "scipy", "A", "dep_one", False)
    asserts.equals(env, "dep_one", owners["scipy"])
    record_annotation(annotations, owners, "scipy", "B", "root", True)
    asserts.equals(env, "B", annotations["scipy"])
    asserts.equals(env, ROOT_MODULE, owners["scipy"])
    return unittest.end(env)

annotation_ownership_test = unittest.make(_annotation_ownership_test_impl)

def extension_test_suite(name):
    """Define the test suite.

    Args:
        name (str): The name of the suite.
    """
    unittest.suite(
        name,
        deps_single_lock_test,
        deps_default_lock_test,
        deps_no_default_lock_test,
        merge_mirrors_test,
        merge_interpreters_test,
        annotation_ownership_test,
    )
