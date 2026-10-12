<!-- Generated with Stardoc: http://skydoc.bazel.build -->

# Bazel rules for `rules_req_compile`

- [py_package_annotation_consumer](#py_package_annotation_consumer)
- [py_package_annotation_target](#py_package_annotation_target)
- [py_package_annotation](#py_package_annotation)
- [py_reqs_compiler](#py_reqs_compiler)
- [py_reqs_solution_test](#py_reqs_solution_test)
- [py_requirements_repository](#py_requirements_repository)
- [sdist_repository](#sdist_repository)
- [whl_repository](#whl_repository)

---
---

<a id="py_package_annotation_consumer"></a>

## py_package_annotation_consumer

<pre>
load("@rules_req_compile//:defs.bzl", "py_package_annotation_consumer")

py_package_annotation_consumer(<a href="#py_package_annotation_consumer-name">name</a>, <a href="#py_package_annotation_consumer-consume">consume</a>, <a href="#py_package_annotation_consumer-package">package</a>)
</pre>

A rule for parsing `annotation_data` targets from a python target.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="py_package_annotation_consumer-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="py_package_annotation_consumer-consume"></a>consume |  The name of the `py_package_annotation` target to parse from `package`.   | String | required |  |
| <a id="py_package_annotation_consumer-package"></a>package |  The python package to parse targets from.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |


<a id="py_package_annotation_target"></a>

## py_package_annotation_target

<pre>
load("@rules_req_compile//:defs.bzl", "py_package_annotation_target")

py_package_annotation_target(<a href="#py_package_annotation_target-name">name</a>, <a href="#py_package_annotation_target-target">target</a>)
</pre>

A container for targets defined by `py_package_annotation` data applied to a python package.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="py_package_annotation_target-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="py_package_annotation_target-target"></a>target |  The target to track in a python package.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |


<a id="py_reqs_compiler"></a>

## py_reqs_compiler

<pre>
load("@rules_req_compile//:defs.bzl", "py_reqs_compiler")

py_reqs_compiler(<a href="#py_reqs_compiler-name">name</a>, <a href="#py_reqs_compiler-allow_sdists">allow_sdists</a>, <a href="#py_reqs_compiler-custom_compile_command">custom_compile_command</a>, <a href="#py_reqs_compiler-platform">platform</a>, <a href="#py_reqs_compiler-python_version">python_version</a>,
                 <a href="#py_reqs_compiler-requirements_in">requirements_in</a>, <a href="#py_reqs_compiler-requirements_txt">requirements_txt</a>)
</pre>

A Bazel rule for compiling python requirements.


```python
load("@rules_req_compile//:defs.bzl", "py_reqs_compiler", "py_reqs_solution_test")

filegroup(
    name = "requriements",
    srcs = ["requirements.in"],
    data = [
        # Any transitive files included via `-r` should be added here.
    ],
)

py_reqs_compiler(
    name = "requirements.update",
    requirements_in = ":requirements",
    requirements_txt = "requirements.txt",
)

```

Updating requirements can be performed by running the new target.

```bash
bazel run //:requirements.update
```

By default the rule will try to recycle pins already existing in the solution file (`requirements.txt`). To perform
a clean resolution (fetching latest for all requirements) the `--upgrade` flag can be used.

```bash
bazel run //:requirements.update -- --upgrade
```

By default a solution is compiled for the platform and Python version running the compiler. The `platform` and
`python_version` attributes compile a solution for a different environment, so solutions for every platform a
project supports can be produced and tested from any machine.

```python
load("@rules_req_compile//:defs.bzl", "py_reqs_compiler", "py_reqs_solution_test")

[
    py_reqs_compiler(
        name = "requirements.{}.update".format(platform),
        platform = platform,
        requirements_in = ":requirements",
        requirements_txt = "requirements.{}.txt".format(platform),
    )
    for platform in [
        "manylinux_2_28_x86_64",
        "macosx_11_0_arm64",
        "win_amd64",
    ]
]

[
    py_reqs_solution_test(
        name = "requirements.{}.test".format(platform),
        compiler = ":requirements.{}.update".format(platform),
    )
    for platform in [
        "manylinux_2_28_x86_64",
        "macosx_11_0_arm64",
        "win_amd64",
    ]
]
```

Wheels are selected and environment markers are evaluated as they would be when installing on the target.
Source distributions (sdists) have their metadata extracted on the machine running the compiler, so solutions
for other platforms should avoid them, which is the default (`allow_sdists = False`).

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="py_reqs_compiler-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="py_reqs_compiler-allow_sdists"></a>allow_sdists |  Whether or not the solution file is allowed to contain sdist packages.   | Boolean | optional |  `False`  |
| <a id="py_reqs_compiler-custom_compile_command"></a>custom_compile_command |  The command to display in the header of the generated lock file (`requirements_txt`). Any references to `{label}` will be replaced with the label of this target.   | String | optional |  `"bazel run \"{label}\""`  |
| <a id="py_reqs_compiler-platform"></a>platform |  The platform to compile the solution for as a wheel platform tag, as accepted by `pip --platform`, e.g. `manylinux_2_28_x86_64`, `manylinux2014_aarch64`, `macosx_11_0_arm64` or `win_amd64`. A manylinux tag accepts wheels for that glibc or older, a macosx tag wheels for that release or older. When unset, the solution is compiled for the platform running the compiler.   | String | optional |  `""`  |
| <a id="py_reqs_compiler-python_version"></a>python_version |  The Python version to compile the solution for, e.g. `3.11.4`. When unset, the exact version of the resolved Python toolchain is used, which keeps the solution independent of the machine running the compiler. A version without a patch number, e.g. `3.9`, is compiled as `3.9.0`.   | String | optional |  `""`  |
| <a id="py_reqs_compiler-requirements_in"></a>requirements_in |  The input requirements file   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |
| <a id="py_reqs_compiler-requirements_txt"></a>requirements_txt |  The solution file.   | <a href="https://bazel.build/concepts/labels">Label</a> | required |  |


<a id="py_reqs_solution_test"></a>

## py_reqs_solution_test

<pre>
load("@rules_req_compile//:defs.bzl", "py_reqs_solution_test")

py_reqs_solution_test(<a href="#py_reqs_solution_test-name">name</a>, <a href="#py_reqs_solution_test-compiler">compiler</a>, <a href="#py_reqs_solution_test-custom_compile_command">custom_compile_command</a>, <a href="#py_reqs_solution_test-requirements_in">requirements_in</a>, <a href="#py_reqs_solution_test-requirements_txt">requirements_txt</a>)
</pre>

A Bazel test rule for ensuring the solution file for a `py_reqs_compiler` target satisifes the given requirements (`requirements_in`).

```python
load("@rules_req_compile//:defs.bzl", "py_reqs_compiler", "py_reqs_solution_test")

py_reqs_compiler(
    name = "requirements.update",
    requirements_in = "requirements.in",
    requirements_txt = "requirements.txt",
)

py_reqs_solution_test(
    name = "requirements_test",
    requirements_in = "requirements.in",
    requirements_txt = "requirements.txt",
)
```

Alternatively, a test can be defined in isolation using just the requirements files:

```python
load("@rules_req_compile//:defs.bzl", "py_reqs_solution_test")

py_reqs_solution_test(
    name = "requirements_test",
    custom_compile_command = "python3 -m req_compile --multiline --hashes --urls --solution requirements.txt requirements.in",
    requirements_in = "requirements.in",
    requirements_txt = "requirements.txt",
)
```

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="py_reqs_solution_test-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="py_reqs_solution_test-compiler"></a>compiler |  The `py_reqs_compiler` target to test. This attribute is mutally exclusive with `requirements_in` and `requirements_txt` and does not do any string formatting like `py_reqs_compiler` does.   | <a href="https://bazel.build/concepts/labels">Label</a> | optional |  `None`  |
| <a id="py_reqs_solution_test-custom_compile_command"></a>custom_compile_command |  The command to display in the header of the generated lock file (`requirements_txt`). This attribute is required with `requirements_in` and `requirements_txt`.   | String | optional |  `""`  |
| <a id="py_reqs_solution_test-requirements_in"></a>requirements_in |  The input requirements file. This attribute is mutually exclusive with `compiler`.   | <a href="https://bazel.build/concepts/labels">Label</a> | optional |  `None`  |
| <a id="py_reqs_solution_test-requirements_txt"></a>requirements_txt |  The solution file. This attribute is mutually exclusive with `compiler`.   | <a href="https://bazel.build/concepts/labels">Label</a> | optional |  `None`  |


<a id="py_package_annotation"></a>

## py_package_annotation

<pre>
load("@rules_req_compile//:defs.bzl", "py_package_annotation")

py_package_annotation(*, <a href="#py_package_annotation-additive_build_file">additive_build_file</a>, <a href="#py_package_annotation-additive_build_file_content">additive_build_file_content</a>, <a href="#py_package_annotation-additive_build_content">additive_build_content</a>,
                      <a href="#py_package_annotation-copy_srcs">copy_srcs</a>, <a href="#py_package_annotation-copy_files">copy_files</a>, <a href="#py_package_annotation-copy_executables">copy_executables</a>, <a href="#py_package_annotation-data">data</a>, <a href="#py_package_annotation-data_exclude_glob">data_exclude_glob</a>,
                      <a href="#py_package_annotation-srcs_exclude_glob">srcs_exclude_glob</a>, <a href="#py_package_annotation-deps">deps</a>, <a href="#py_package_annotation-deps_excludes">deps_excludes</a>, <a href="#py_package_annotation-patches">patches</a>)
</pre>

Annotations to apply to the BUILD file content from package generated from a `pip_repository` rule.

[cf]: https://github.com/bazelbuild/bazel-skylib/blob/main/docs/copy_file_doc.md


**PARAMETERS**


| Name  | Description | Default Value |
| :------------- | :------------- | :------------- |
| <a id="py_package_annotation-additive_build_file"></a>additive_build_file |  The label of a `BUILD` file to add to the generated one for a pacakge.   |  `None` |
| <a id="py_package_annotation-additive_build_file_content"></a>additive_build_file_content |  Raw text to add to the generated `BUILD` file of a package.   |  `None` |
| <a id="py_package_annotation-additive_build_content"></a>additive_build_content |  __DEPRECATED__ use `additive_build_file_content` instead.   |  `None` |
| <a id="py_package_annotation-copy_srcs"></a>copy_srcs |  A mapping of `src` and `out` files for [@bazel_skylib//rules:copy_file.bzl][cf]. The output files are added to the `py_library.srcs` attribute.   |  `{}` |
| <a id="py_package_annotation-copy_files"></a>copy_files |  A mapping of `src` and `out` files for [@bazel_skylib//rules:copy_file.bzl][cf]. The output files are added to the `py_library.data` attribute.   |  `{}` |
| <a id="py_package_annotation-copy_executables"></a>copy_executables |  A mapping of `src` and `out` files for [@bazel_skylib//rules:copy_file.bzl][cf]. Targets generated here will also be flagged as executable.   |  `{}` |
| <a id="py_package_annotation-data"></a>data |  A list of labels to add as `data` dependencies to the generated `py_library` target.   |  `[]` |
| <a id="py_package_annotation-data_exclude_glob"></a>data_exclude_glob |  A list of exclude glob patterns to add as `data` to the generated `py_library` target.   |  `[]` |
| <a id="py_package_annotation-srcs_exclude_glob"></a>srcs_exclude_glob |  A list of labels to add as `srcs` to the generated `py_library` target.   |  `[]` |
| <a id="py_package_annotation-deps"></a>deps |  A list of dependencies to include to the package. Can be other packages or labels.   |  `[]` |
| <a id="py_package_annotation-deps_excludes"></a>deps_excludes |  A list of packages to exclude from the package. (In cases where a package has circular dependencies).   |  `[]` |
| <a id="py_package_annotation-patches"></a>patches |  A list of patch files to apply to the wheel.   |  `[]` |

**RETURNS**

str: A json encoded string of the provided content.


<a id="py_requirements_repository"></a>

## py_requirements_repository

<pre>
load("@rules_req_compile//:defs.bzl", "py_requirements_repository")

py_requirements_repository(<a href="#py_requirements_repository-name">name</a>, <a href="#py_requirements_repository-annotations">annotations</a>, <a href="#py_requirements_repository-defs_id_map">defs_id_map</a>, <a href="#py_requirements_repository-hub_name">hub_name</a>, <a href="#py_requirements_repository-interpreter">interpreter</a>,
                           <a href="#py_requirements_repository-legacy_root_pkg_aliases">legacy_root_pkg_aliases</a>, <a href="#py_requirements_repository-package_aliases">package_aliases</a>, <a href="#py_requirements_repository-requirements_lock">requirements_lock</a>,
                           <a href="#py_requirements_repository-requirements_locks">requirements_locks</a>)
</pre>

A rule for importing `requirements.txt` dependencies into Bazel.

Those dependencies become available in a generated `defs.bzl` file.

```python
load("@rules_req_compile//:defs.bzl", "py_requirements_repository")

py_requirements_repository(
    name = "py_requirements",
    requirements_lock = ":requirements.txt",
)

load("@py_requirements//:defs.bzl", "repositories")

repositories()
```

You can then reference installed dependencies from a `BUILD` file with:

```python
load("@py_requirements//:defs.bzl", "requirement")

py_library(
    name = "bar",
    ...
    deps = [
        "//my/other:dep",
        requirement("requests"),
        requirement("numpy"),
    ],
)
```

In addition to the `requirement` macro, which is used to access the generated `py_library`
target generated from a package's wheel, The generated `requirements.bzl` file contains
functionality for exposing [entry points][whl_ep] as `py_binary` targets as well.

[whl_ep]: https://packaging.python.org/specifications/entry-points/

```python
load("@py_requirements//:defs.bzl", "entry_point")

alias(
    name = "pip-compile",
    actual = entry_point(
        pkg = "pip-tools",
        script = "pip-compile",
    ),
)
```

Note that for packages whose name and script are the same, only the name of the package
is needed when calling the `entry_point` macro.

```python
load("@py_requirements//:defs.bzl", "entry_point")

alias(
    name = "flake8",
    actual = entry_point("flake8"),
)
```

A very important detail for generating python dependencies is sdist (source distribution)
dependencies are assumed to be incapable of yielding deterministic outputs. Therefore, any
case where a sdist (source distribution) is found in a solution file passed to either
`requirements_lock` or `requirements_locks`, the dependencies should not be considered
byte-for-byte reproducible. It is highly recommended solution files contain all wheels
so the generated repositories are byte-for-byte consistent. Failure to use binary-only
dependencies will result in unexpected cache invalidation as well as inconsistent or broken
cross-platform behavior when using `requirements_locks`.

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="py_requirements_repository-name"></a>name |  A unique name for this repository.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="py_requirements_repository-alias_of"></a>alias_of |  The name of a hub every package of this hub is an alias of. Used to override the hubs of dependent modules.   | String | optional |  `""`  |
| <a id="py_requirements_repository-default_lock"></a>default_lock |  The id of the lock used when no lock of the hub matches the configuration.   | String | optional |  `""`  |
| <a id="py_requirements_repository-hub_name"></a>hub_name |  Name of the hub repository to generate. Do not use directly.   | String | optional |  `""`  |
| <a id="py_requirements_repository-legacy_root_pkg_aliases"></a>legacy_root_pkg_aliases |  If True, creates aliases in the root BUILD.bazel file pointing to the package targets in their subpackages. This provides backward compatibility for code that references packages at the root (e.g., `@repo//:package_name`).   | Boolean | optional |  `False`  |
| <a id="py_requirements_repository-locks"></a>locks |  A json encoded list of the locks of the hub and how each is selected.   | String | required |  |
| <a id="py_requirements_repository-package_aliases"></a>package_aliases |  Packages to override with a local `py_library`.   | <a href="https://bazel.build/rules/lib/dict">Dictionary: Label -> String</a> | optional |  `{}`  |
| <a id="py_requirements_repository-packages"></a>packages |  A json encoded mapping of package names to the version and `whl_repository` resolved by each lock.   | String | required |  |


<a id="whl_repository"></a>

## whl_repository

<pre>
load("@rules_req_compile//:defs.bzl", "whl_repository")

whl_repository(<a href="#whl_repository-name">name</a>, <a href="#whl_repository-deps">deps</a>, <a href="#whl_repository-annotations">annotations</a>, <a href="#whl_repository-constraint">constraint</a>, <a href="#whl_repository-hub_name">hub_name</a>, <a href="#whl_repository-interpreter">interpreter</a>, <a href="#whl_repository-package">package</a>, <a href="#whl_repository-patches">patches</a>,
               <a href="#whl_repository-sdist_deps_repos">sdist_deps_repos</a>, <a href="#whl_repository-sha256">sha256</a>, <a href="#whl_repository-urls">urls</a>, <a href="#whl_repository-version">version</a>, <a href="#whl_repository-whl">whl</a>)
</pre>

A repository rule for extracting a python [wheel](https://peps.python.org/pep-0491/) and defining a `py_library`.

This repository is expected to be generated by [py_requirements_repository](#py_requirements_repository).

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="whl_repository-name"></a>name |  A unique name for this repository.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="whl_repository-annotations"></a>annotations |  See [py_requirements_repository.annotation](#py_requirements_repository.annotation)   | String | optional |  `"{}"`  |
| <a id="whl_repository-hubs"></a>hubs |  A json encoded mapping of hub names to the locks of the hub using this wheel. Each lock maps its id to the `deps` (python package names) resolved for the package and the `config_setting` label the hub uses to select the lock, which is `null` for hubs with a single lock.   | String | optional |  `"{}"`  |
| <a id="whl_repository-interpreter"></a>interpreter |  Optional Python interpreter binary to use for building sdists.   | <a href="https://bazel.build/concepts/labels">Label</a> | optional |  `None`  |
| <a id="whl_repository-package"></a>package |  The name of the python package the wheel represents.   | String | required |  |
| <a id="whl_repository-patches"></a>patches |  Patches to apply to the installed wheel.   | <a href="https://bazel.build/concepts/labels">List of labels</a> | optional |  `[]`  |
| <a id="whl_repository-sdist_deps_repos"></a>sdist_deps_repos |  INTERNAL: DO NOT USE. Default dependencies for building source distributions.   | <a href="https://bazel.build/concepts/labels">List of labels</a> | optional |  `["@req_compile_sdist_compiler__pip//:pkg", "@req_compile_sdist_compiler__setuptools//:pkg", "@req_compile_sdist_compiler__wheel//:pkg"]`  |
| <a id="whl_repository-sha256"></a>sha256 |  The expected SHA-256 of the file downloaded.   | String | optional |  `""`  |
| <a id="whl_repository-urls"></a>urls |  A list of URLs to the python wheel.   | List of strings | optional |  `[]`  |
| <a id="whl_repository-version"></a>version |  The version of the python package.   | String | required |  |
| <a id="whl_repository-whl"></a>whl |  The label to a wheel.   | <a href="https://bazel.build/concepts/labels">Label</a> | optional |  `None`  |


