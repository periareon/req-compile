"""Starlark unit tests for the planning done by the `requirements` extension."""

# buildifier: disable=bzl-visibility
load("@bazel_skylib//lib:unittest.bzl", "asserts", "unittest")

# buildifier: disable=bzl-visibility
load("//req_compile/private:annotation_utils.bzl", "ROOT_MODULE", "deserialize_package_annotation", "record_annotation")

# buildifier: disable=bzl-visibility
load("//req_compile/private:reqs_repo.bzl", "is_sdist", "merge_wheel")

# buildifier: disable=bzl-visibility
load(
    "//req_compile/private:whl_repo.bzl",
    "declared_license",
    "hub_deps",
    "parse_metadata_license",
    "render_deps",
    "render_package_metadata",
    "wheel_purl",
)

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

def _wheel_purl_test_impl(ctx):
    env = unittest.begin(ctx)

    # The name is normalized the way the purl spec asks for PyPI.
    asserts.equals(env, "pkg:pypi/ast-serialize@0.13.1", wheel_purl("ast_serialize", "0.13.1"))
    asserts.equals(env, "pkg:pypi/click@8.1.7", wheel_purl("Click", "8.1.7"))

    # The distribution the lock pinned, with the hash repeated in the fragment
    # of its URL left out. The encoding is the builder's: of the characters
    # the purl spec allows in a qualifier value, `/` is still encoded.
    asserts.equals(
        env,
        "pkg:pypi/click@8.1.7" +
        "?checksum=sha256:" + "a" * 64 +
        "&download_url=https:%2F%2Fpypi.org%2Fclick-8.1.7-py3-none-any.whl" +
        "&file_name=click-8.1.7-py3-none-any.whl",
        wheel_purl(
            "click",
            "8.1.7",
            file_name = "click-8.1.7-py3-none-any.whl",
            url = "https://pypi.org/click-8.1.7-py3-none-any.whl#sha256=" + "a" * 64,
            sha256 = "a" * 64,
        ),
    )
    return unittest.end(env)

wheel_purl_test = unittest.make(_wheel_purl_test_impl)

_SPDX = {
    "apache-2.0": "Apache-2.0",
    "mit": "MIT",
    "mpl-2.0": "MPL-2.0",
}

# The kinds are named canonically, which a wheel repository can resolve
# without seeing `@package_metadata`.
_MIT = str(Label("@package_metadata//licenses/spdx:MIT"))

# The rules are loaded from this module, for the same reason.
_METADATA_RULES = str(Label("//req_compile/private:package_metadata.bzl"))

def _metadata_license_test_impl(ctx):
    env = unittest.begin(ctx)

    # PEP 639: the expression decides, the license files are named.
    metadata = parse_metadata_license("""\
Metadata-Version: 2.4
Name: idna
Version: 3.20
License-Expression: MIT
License-File: LICENSE.md
Classifier: License :: OSI Approved :: MIT License

A description, with a License: header of its own that is not read.
""")
    asserts.equals(env, "MIT", metadata.expression)
    asserts.equals(env, None, metadata.license)
    asserts.equals(env, ["LICENSE.md"], metadata.files)
    asserts.equals(env, ["License :: OSI Approved :: MIT License"], metadata.classifiers)
    declared = declared_license(metadata, _SPDX)
    asserts.equals(env, "MIT", declared.identifier)
    asserts.equals(env, _MIT, declared.kind)

    # A compound expression is kept as is, without a kind to point at.
    metadata = parse_metadata_license("License-Expression: MIT AND Apache-2.0\n")
    declared = declared_license(metadata, _SPDX)
    asserts.equals(env, "MIT AND Apache-2.0", declared.identifier)
    asserts.equals(env, None, declared.kind)

    # The free-form field counts when it is exactly an identifier, whatever its case.
    metadata = parse_metadata_license("License: mpl-2.0\nLicense-File: LICENSE\n")
    asserts.equals(env, "MPL-2.0", declared_license(metadata, _SPDX).identifier)

    # Otherwise an unambiguous classifier does. Continuations and the
    # placeholder of older setuptools are not a license.
    metadata = parse_metadata_license("""\
License: UNKNOWN
Classifier: License :: OSI Approved :: BSD License
Classifier: License :: OSI Approved :: Apache Software License
Description: Something
        continued.
""")
    asserts.equals(env, None, metadata.license)
    asserts.equals(env, "Apache-2.0", declared_license(metadata, _SPDX).identifier)

    # A license nothing names.
    metadata = parse_metadata_license("License: Proprietary\n")
    asserts.equals(env, "Proprietary", metadata.license)
    asserts.equals(env, None, declared_license(metadata, _SPDX))
    return unittest.end(env)

metadata_license_test = unittest.make(_metadata_license_test_impl)

def _render_package_metadata_test_impl(ctx):
    env = unittest.begin(ctx)

    # Nothing declared: the purl alone. The templates come out of this file
    # with the line endings it was checked out with, so no needle spans a line.
    rendered = render_package_metadata("pkg:pypi/click@8.1.7", None)
    asserts.equals(env, 'load("{}", "package_metadata")\n'.format(_METADATA_RULES), rendered.loads)
    asserts.true(env, '    purl = "pkg:pypi/click@8.1.7",' in rendered.content, rendered.content)
    asserts.true(env, "    attributes = []," in rendered.content, rendered.content)
    asserts.false(env, "license(" in rendered.content, rendered.content)

    # A known license points at the kind of `@package_metadata`.
    rendered = render_package_metadata("pkg:pypi/click@8.1.7", struct(
        kind = _MIT,
        identifier = "MIT",
        full_name = "MIT",
        text = "site-packages/click-8.1.7.dist-info/licenses/LICENSE",
    ))
    asserts.equals(env, 'load("{}", "license", "package_metadata")\n'.format(_METADATA_RULES), rendered.loads)
    asserts.true(env, '    attributes = [":license"],' in rendered.content, rendered.content)
    asserts.true(env, '    kind = "{}",'.format(_MIT) in rendered.content, rendered.content)
    asserts.true(env, '    text = "site-packages/click-8.1.7.dist-info/licenses/LICENSE",' in rendered.content, rendered.content)

    # One it has no kind for declares its own, and a license without a text has none.
    rendered = render_package_metadata("pkg:pypi/click@8.1.7", struct(
        kind = None,
        identifier = "MIT AND Apache-2.0",
        full_name = "MIT AND Apache-2.0",
        text = None,
    ))
    asserts.equals(env, 'load("{}", "license", "license_kind", "package_metadata")\n'.format(_METADATA_RULES), rendered.loads)
    asserts.true(env, '    identifier = "MIT AND Apache-2.0",' in rendered.content, rendered.content)
    asserts.true(env, '    kind = ":license_kind",' in rendered.content, rendered.content)
    asserts.true(env, "    text = None," in rendered.content, rendered.content)
    return unittest.end(env)

render_package_metadata_test = unittest.make(_render_package_metadata_test_impl)

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
        wheel_purl_test,
        metadata_license_test,
        render_package_metadata_test,
    )
