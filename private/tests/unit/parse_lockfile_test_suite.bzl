"""Starlark unit tests for `parse_lockfile`."""

load("@bazel_skylib//lib:unittest.bzl", "asserts", "unittest")
load("//private:reqs_repo.bzl", "parse_lockfile")

def _parse_lockfile_test_impl(ctx):
    env = unittest.begin(ctx)

    constraints = parse_lockfile(
        content = ctx.attr.content,
        repository_name = "parse_lockfile_test",
        annotations = {},
        lockfile = Label(ctx.attr.mock_lockfile),
    )

    for name, constraint in constraints.items():
        # These values differ between bzlmod and workspace
        if constraint["whl"]:
            constraint.pop("whl")

    asserts.equals(
        env,
        json.decode(ctx.attr.expected),
        constraints,
    )

    return unittest.end(env)

parse_lockfile_test = unittest.make(
    _parse_lockfile_test_impl,
    attrs = {
        "content": attr.string(
            doc = "The text content of a requirements lock file",
            mandatory = True,
        ),
        "expected": attr.string(
            doc = "A json encoded string of parsed requirements",
            mandatory = True,
        ),
        "mock_lockfile": attr.string(
            doc = "A fake label to a madeup location for the solution file.",
            default = "@req_compile_fake//:solution.txt",
        ),
    },
)

def _parse_lockfile_test(name, **kwargs):
    parse_lockfile_test(
        name = name,
        **kwargs
    )

    return name

_SIMPLE_CONTENT = r"""
pycparser==2.22 \
    --hash=sha256:c3702b6d3dd8c7abc1afa565d7e63d53a1d0bd86cdc24edd75470f4de499cfcc
    # via requirements.in
    # https://files.pythonhosted.org/packages/13/a3/a812df4e2dd5696d1f351d58b8fe16a405b234ad2886a0dab9183fb78109/pycparser-2.22-py3-none-any.whl#sha256=c3702b6d3dd8c7abc1afa565d7e63d53a1d0bd86cdc24edd75470f4de499cfcc
"""

_SIMPLE_EXPECTED = {
    "pycparser": {
        "annotations": {},
        "constraint": None,
        "deps": [],
        "package": "pycparser",
        "sha256": "c3702b6d3dd8c7abc1afa565d7e63d53a1d0bd86cdc24edd75470f4de499cfcc",
        "url": "https://files.pythonhosted.org/packages/13/a3/a812df4e2dd5696d1f351d58b8fe16a405b234ad2886a0dab9183fb78109/pycparser-2.22-py3-none-any.whl#sha256=c3702b6d3dd8c7abc1afa565d7e63d53a1d0bd86cdc24edd75470f4de499cfcc",
        "version": "2.22",
        "via": [
            "requirements_in",
        ],
        "whl": None,
    },
}

_WITH_DEPS_CONTENT = r"""
certifi==2024.2.2 \
    --hash=sha256:dc383c07b76109f368f6106eee2b593b04a011ea4d55f652c6ca24a754d1cdd1
    # via requests (>=2017.4.17)
    # https://files.pythonhosted.org/packages/ba/06/a07f096c664aeb9f01624f858c3add0a4e913d6c96257acb4fce61e7de14/certifi-2024.2.2-py3-none-any.whl#sha256=dc383c07b76109f368f6106eee2b593b04a011ea4d55f652c6ca24a754d1cdd1
cffi==1.16.0 \
    --hash=sha256:1b8ebc27c014c59692bb2664c7d13ce7a6e9a629be20e54e7271fa696ff2b417
    # via cryptography (>=1.12)
    # https://files.pythonhosted.org/packages/18/6c/0406611f3d5aadf4c5b08f6c095d874aed8dfc2d3a19892707d72536d5dc/cffi-1.16.0-cp311-cp311-macosx_11_0_arm64.whl#sha256=1b8ebc27c014c59692bb2664c7d13ce7a6e9a629be20e54e7271fa696ff2b417
charset-normalizer==3.3.2 \
    --hash=sha256:549a3a73da901d5bc3ce8d24e0600d1fa85524c10287f6004fbab87672bf3e1e
    # via requests (<4,>=2)
    # https://files.pythonhosted.org/packages/dd/51/68b61b90b24ca35495956b718f35a9756ef7d3dd4b3c1508056fa98d1a1b/charset_normalizer-3.3.2-cp311-cp311-macosx_11_0_arm64.whl#sha256=549a3a73da901d5bc3ce8d24e0600d1fa85524c10287f6004fbab87672bf3e1e
cryptography==42.0.5 \
    --hash=sha256:5e6275c09d2badf57aea3afa80d975444f4be8d3bc58f7f80d2a484c6f9485c8
    # via test.in
    # https://files.pythonhosted.org/packages/6d/4d/f7c14c7a49e35df829e04d451a57b843208be7442c8e087250c195775be1/cryptography-42.0.5-cp39-abi3-macosx_10_12_universal2.whl#sha256=5e6275c09d2badf57aea3afa80d975444f4be8d3bc58f7f80d2a484c6f9485c8
idna==3.6 \
    --hash=sha256:c05567e9c24a6b9faaa835c4821bad0590fbb9d5779e7caa6e1cc4978e7eb24f
    # via requests (<4,>=2.5)
    # https://files.pythonhosted.org/packages/c2/e7/a82b05cf63a603df6e68d59ae6a68bf5064484a0718ea5033660af4b54a9/idna-3.6-py3-none-any.whl#sha256=c05567e9c24a6b9faaa835c4821bad0590fbb9d5779e7caa6e1cc4978e7eb24f
pycparser==2.22 \
    --hash=sha256:c3702b6d3dd8c7abc1afa565d7e63d53a1d0bd86cdc24edd75470f4de499cfcc
    # via cffi
    # https://files.pythonhosted.org/packages/13/a3/a812df4e2dd5696d1f351d58b8fe16a405b234ad2886a0dab9183fb78109/pycparser-2.22-py3-none-any.whl#sha256=c3702b6d3dd8c7abc1afa565d7e63d53a1d0bd86cdc24edd75470f4de499cfcc
requests==2.31.0 \
    --hash=sha256:58cd2187c01e70e6e26505bca751777aa9f2ee0b7f4300988b709f44e013003f
    # via test.in
    # https://files.pythonhosted.org/packages/70/8e/0e2d847013cb52cd35b38c009bb167a1a26b2ce6cd6965bf26b47bc0bf44/requests-2.31.0-py3-none-any.whl#sha256=58cd2187c01e70e6e26505bca751777aa9f2ee0b7f4300988b709f44e013003f
urllib3==2.2.1 \
    --hash=sha256:450b20ec296a467077128bff42b73080516e71b56ff59a60a02bef2232c4fa9d
    # via requests (<3,>=1.21.1)
    # https://files.pythonhosted.org/packages/a2/73/a68704750a7679d0b6d3ad7aa8d4da8e14e151ae82e6fee774e6e0d05ec8/urllib3-2.2.1-py3-none-any.whl#sha256=450b20ec296a467077128bff42b73080516e71b56ff59a60a02bef2232c4fa9d
"""

_WITH_DEPS_EXPECTED = {
    "certifi": {
        "annotations": {},
        "constraint": None,
        "deps": [],
        "package": "certifi",
        "sha256": "dc383c07b76109f368f6106eee2b593b04a011ea4d55f652c6ca24a754d1cdd1",
        "url": "https://files.pythonhosted.org/packages/ba/06/a07f096c664aeb9f01624f858c3add0a4e913d6c96257acb4fce61e7de14/certifi-2024.2.2-py3-none-any.whl#sha256=dc383c07b76109f368f6106eee2b593b04a011ea4d55f652c6ca24a754d1cdd1",
        "version": "2024.2.2",
        "via": [
            "requests",
        ],
        "whl": None,
    },
    "cffi": {
        "annotations": {},
        "constraint": None,
        "deps": [
            "pycparser",
        ],
        "package": "cffi",
        "sha256": "1b8ebc27c014c59692bb2664c7d13ce7a6e9a629be20e54e7271fa696ff2b417",
        "url": "https://files.pythonhosted.org/packages/18/6c/0406611f3d5aadf4c5b08f6c095d874aed8dfc2d3a19892707d72536d5dc/cffi-1.16.0-cp311-cp311-macosx_11_0_arm64.whl#sha256=1b8ebc27c014c59692bb2664c7d13ce7a6e9a629be20e54e7271fa696ff2b417",
        "version": "1.16.0",
        "via": [
            "cryptography",
        ],
        "whl": None,
    },
    "charset_normalizer": {
        "annotations": {},
        "constraint": None,
        "deps": [],
        "package": "charset-normalizer",
        "sha256": "549a3a73da901d5bc3ce8d24e0600d1fa85524c10287f6004fbab87672bf3e1e",
        "url": "https://files.pythonhosted.org/packages/dd/51/68b61b90b24ca35495956b718f35a9756ef7d3dd4b3c1508056fa98d1a1b/charset_normalizer-3.3.2-cp311-cp311-macosx_11_0_arm64.whl#sha256=549a3a73da901d5bc3ce8d24e0600d1fa85524c10287f6004fbab87672bf3e1e",
        "version": "3.3.2",
        "via": [
            "requests",
        ],
        "whl": None,
    },
    "cryptography": {
        "annotations": {},
        "constraint": None,
        "deps": [
            "cffi",
        ],
        "package": "cryptography",
        "sha256": "5e6275c09d2badf57aea3afa80d975444f4be8d3bc58f7f80d2a484c6f9485c8",
        "url": "https://files.pythonhosted.org/packages/6d/4d/f7c14c7a49e35df829e04d451a57b843208be7442c8e087250c195775be1/cryptography-42.0.5-cp39-abi3-macosx_10_12_universal2.whl#sha256=5e6275c09d2badf57aea3afa80d975444f4be8d3bc58f7f80d2a484c6f9485c8",
        "version": "42.0.5",
        "via": [
            "test_in",
        ],
        "whl": None,
    },
    "idna": {
        "annotations": {},
        "constraint": None,
        "deps": [],
        "package": "idna",
        "sha256": "c05567e9c24a6b9faaa835c4821bad0590fbb9d5779e7caa6e1cc4978e7eb24f",
        "url": "https://files.pythonhosted.org/packages/c2/e7/a82b05cf63a603df6e68d59ae6a68bf5064484a0718ea5033660af4b54a9/idna-3.6-py3-none-any.whl#sha256=c05567e9c24a6b9faaa835c4821bad0590fbb9d5779e7caa6e1cc4978e7eb24f",
        "version": "3.6",
        "via": [
            "requests",
        ],
        "whl": None,
    },
    "pycparser": {
        "annotations": {},
        "constraint": None,
        "deps": [],
        "package": "pycparser",
        "sha256": "c3702b6d3dd8c7abc1afa565d7e63d53a1d0bd86cdc24edd75470f4de499cfcc",
        "url": "https://files.pythonhosted.org/packages/13/a3/a812df4e2dd5696d1f351d58b8fe16a405b234ad2886a0dab9183fb78109/pycparser-2.22-py3-none-any.whl#sha256=c3702b6d3dd8c7abc1afa565d7e63d53a1d0bd86cdc24edd75470f4de499cfcc",
        "version": "2.22",
        "via": [
            "cffi",
        ],
        "whl": None,
    },
    "requests": {
        "annotations": {},
        "constraint": None,
        "deps": [
            "certifi",
            "charset_normalizer",
            "idna",
            "urllib3",
        ],
        "package": "requests",
        "sha256": "58cd2187c01e70e6e26505bca751777aa9f2ee0b7f4300988b709f44e013003f",
        "url": "https://files.pythonhosted.org/packages/70/8e/0e2d847013cb52cd35b38c009bb167a1a26b2ce6cd6965bf26b47bc0bf44/requests-2.31.0-py3-none-any.whl#sha256=58cd2187c01e70e6e26505bca751777aa9f2ee0b7f4300988b709f44e013003f",
        "version": "2.31.0",
        "via": [
            "test_in",
        ],
        "whl": None,
    },
    "urllib3": {
        "annotations": {},
        "constraint": None,
        "deps": [],
        "package": "urllib3",
        "sha256": "450b20ec296a467077128bff42b73080516e71b56ff59a60a02bef2232c4fa9d",
        "url": "https://files.pythonhosted.org/packages/a2/73/a68704750a7679d0b6d3ad7aa8d4da8e14e151ae82e6fee774e6e0d05ec8/urllib3-2.2.1-py3-none-any.whl#sha256=450b20ec296a467077128bff42b73080516e71b56ff59a60a02bef2232c4fa9d",
        "version": "2.2.1",
        "via": [
            "requests",
        ],
        "whl": None,
    },
}

_WITH_HEADER_CONTENT = """\
# Some text content at the top

--index-url https://pypi.com
--extra-index-url https://pypi2.com
--extra-index-url https://pypi3.com

""" + _WITH_DEPS_CONTENT

_WITH_HEADER_EXPECTED = _WITH_DEPS_EXPECTED

_FIND_LINKS_CONTENT = r"""
--find-links wheeldir

py4j==0.10.9.7 \
    --hash=sha256:85defdfd2b2376eb3abf5ca6474b51ab7e0de341c75a02f46dc9b5976f5a5c1b
    # via pyspark (==0.10.9.7)
    # https://files.pythonhosted.org/packages/10/30/a58b32568f1623aaad7db22aa9eafc4c6c194b429ff35bdc55ca2726da47/py4j-0.10.9.7-py2.py3-none-any.whl#sha256=85defdfd2b2376eb3abf5ca6474b51ab7e0de341c75a02f46dc9b5976f5a5c1b
pyspark==3.5.1 \
    --hash=sha256:810546bb58f2aff5f51ee5c8389d936c9c8ba4c27ddace1c4a87e48635b8812a
    # via requirements.in
    # wheeldir/pyspark-3.5.1-py2.py3-none-any.whl
"""

_FIND_LINKS_EXPECTED = {
    "py4j": {
        "annotations": {},
        "constraint": None,
        "deps": [],
        "package": "py4j",
        "sha256": "85defdfd2b2376eb3abf5ca6474b51ab7e0de341c75a02f46dc9b5976f5a5c1b",
        "url": "https://files.pythonhosted.org/packages/10/30/a58b32568f1623aaad7db22aa9eafc4c6c194b429ff35bdc55ca2726da47/py4j-0.10.9.7-py2.py3-none-any.whl#sha256=85defdfd2b2376eb3abf5ca6474b51ab7e0de341c75a02f46dc9b5976f5a5c1b",
        "version": "0.10.9.7",
        "via": [
            "pyspark",
        ],
        "whl": None,
    },
    "pyspark": {
        "annotations": {},
        "constraint": None,
        "deps": [
            "py4j",
        ],
        "package": "pyspark",
        "sha256": "810546bb58f2aff5f51ee5c8389d936c9c8ba4c27ddace1c4a87e48635b8812a",
        "url": None,
        "version": "3.5.1",
        "via": [
            "requirements_in",
        ],
    },
}

_FIND_LINKS_NESTED_CONTENT = _FIND_LINKS_CONTENT.replace("wheeldir", "../wheeldir").replace("requirements.in", "nested/requirements.in")

_FIND_LINKS_NESTED_EXPECTED = {
    "py4j": {
        "annotations": {},
        "constraint": None,
        "deps": [],
        "package": "py4j",
        "sha256": "85defdfd2b2376eb3abf5ca6474b51ab7e0de341c75a02f46dc9b5976f5a5c1b",
        "url": "https://files.pythonhosted.org/packages/10/30/a58b32568f1623aaad7db22aa9eafc4c6c194b429ff35bdc55ca2726da47/py4j-0.10.9.7-py2.py3-none-any.whl#sha256=85defdfd2b2376eb3abf5ca6474b51ab7e0de341c75a02f46dc9b5976f5a5c1b",
        "version": "0.10.9.7",
        "via": [
            "pyspark",
        ],
        "whl": None,
    },
    "pyspark": {
        "annotations": {},
        "constraint": None,
        "deps": [
            "py4j",
        ],
        "package": "pyspark",
        "sha256": "810546bb58f2aff5f51ee5c8389d936c9c8ba4c27ddace1c4a87e48635b8812a",
        "url": None,
        "version": "3.5.1",
        "via": [],
    },
}

def parse_lockfile_test_suite(name, **kwargs):
    """Define a test suite for requirements repository lockfile parsing logic.

    Args:
        name (str): The name of the test suite.
        **kwargs (dict): Additional keyword arguments.
    """
    tests = [
        _parse_lockfile_test(
            name = "empty_test",
            content = "",
            expected = json.encode({}),
        ),
        _parse_lockfile_test(
            name = "simple_test",
            content = _SIMPLE_CONTENT,
            expected = json.encode(_SIMPLE_EXPECTED),
        ),
        _parse_lockfile_test(
            name = "with_deps_test",
            content = _WITH_DEPS_CONTENT,
            expected = json.encode(_WITH_DEPS_EXPECTED),
        ),
        _parse_lockfile_test(
            name = "with_header_test",
            content = _WITH_HEADER_CONTENT,
            expected = json.encode(_WITH_HEADER_EXPECTED),
        ),
        _parse_lockfile_test(
            name = "find_links_test",
            content = _FIND_LINKS_CONTENT,
            expected = json.encode(_FIND_LINKS_EXPECTED),
        ),
        _parse_lockfile_test(
            name = "find_links_nested_test",
            content = _FIND_LINKS_NESTED_CONTENT,
            expected = json.encode(_FIND_LINKS_NESTED_EXPECTED),
            mock_lockfile = "@req_compile_fake//nested:solution.txt",
        ),
    ]

    native.test_suite(
        name = name,
        tests = tests,
        **kwargs
    )
