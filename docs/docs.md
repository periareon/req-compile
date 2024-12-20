<!-- Generated with Stardoc: http://skydoc.bazel.build -->

# Bazel rules for `rules_req_compile`

## Setup

```python
load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

http_archive(
    name = "rules_req_compile",
    sha256 = "{see_release}",
    urls = ["{see_release}"],
)

load("@rules_req_compile//:repositories.bzl", "req_compile_dependencies")

req_compile_dependencies()

load("@rules_req_compile//:repositories_transitive.bzl", "req_compile_transitive_dependencies")

req_compile_transitive_dependencies()
```

## Rules

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

py_reqs_compiler(<a href="#py_reqs_compiler-name">name</a>, <a href="#py_reqs_compiler-allow_sdists">allow_sdists</a>, <a href="#py_reqs_compiler-custom_compile_command">custom_compile_command</a>, <a href="#py_reqs_compiler-requirements_in">requirements_in</a>, <a href="#py_reqs_compiler-requirements_txt">requirements_txt</a>)
</pre>

A Bazel rule for compiling python requirements for the current platform.


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

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="py_reqs_compiler-name"></a>name |  A unique name for this target.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="py_reqs_compiler-allow_sdists"></a>allow_sdists |  Whether or not the solution file is allowed to contain sdist packages.   | Boolean | optional |  `False`  |
| <a id="py_reqs_compiler-custom_compile_command"></a>custom_compile_command |  The command to display in the header of the generated lock file (`requirements_txt`). Any references to `{label}` will be replaced with the label of this target.   | String | optional |  `"bazel run \"{label}\""`  |
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

py_package_annotation(<a href="#py_package_annotation-additive_build_file">additive_build_file</a>, <a href="#py_package_annotation-additive_build_file_content">additive_build_file_content</a>, <a href="#py_package_annotation-additive_build_content">additive_build_content</a>,
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

py_requirements_repository(<a href="#py_requirements_repository-name">name</a>, <a href="#py_requirements_repository-annotations">annotations</a>, <a href="#py_requirements_repository-hub_name">hub_name</a>, <a href="#py_requirements_repository-interpreter">interpreter</a>, <a href="#py_requirements_repository-repo_mapping">repo_mapping</a>,
                           <a href="#py_requirements_repository-requirements_lock">requirements_lock</a>, <a href="#py_requirements_repository-requirements_locks">requirements_locks</a>)
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
| <a id="py_requirements_repository-annotations"></a>annotations |  Optional annotations to apply to packages. For details see [@rules_python//python:pip.bzl%package_annotation](https://github.com/bazelbuild/rules_python/blob/main/docs/pip_repository.md#package_annotation)   | <a href="https://bazel.build/rules/lib/dict">Dictionary: String -> String</a> | optional |  `{}`  |
| <a id="py_requirements_repository-hub_name"></a>hub_name |  Name of the hub repository to generate. Do not use directly.   | String | optional |  `""`  |
| <a id="py_requirements_repository-interpreter"></a>interpreter |  The label of a python interpreter to use for compiling source distributions (sdists). If this is not provided then the provided lock file must represent binary-only dependencies. Note that should this interpreter be needed (a sdist was found in `requirements_lock` or `requirements_locks`), the dependencies generated may not be byte-for-byte reproducible and users may experience unexpected cache invalidation or unexpected cross-platform behavior.   | <a href="https://bazel.build/concepts/labels">Label</a> | optional |  `None`  |
| <a id="py_requirements_repository-repo_mapping"></a>repo_mapping |  In `WORKSPACE` context only: a dictionary from local repository name to global repository name. This allows controls over workspace dependency resolution for dependencies of this repository.<br><br>For example, an entry `"@foo": "@bar"` declares that, for any time this repository depends on `@foo` (such as a dependency on `@foo//some:target`, it should actually resolve that dependency within globally-declared `@bar` (`@bar//some:target`).<br><br>This attribute is _not_ supported in `MODULE.bazel` context (when invoking a repository rule inside a module extension's implementation function).   | <a href="https://bazel.build/rules/lib/dict">Dictionary: String -> String</a> | optional |  |
| <a id="py_requirements_repository-requirements_lock"></a>requirements_lock |  A fully resolved 'requirements.txt' pip requirement file containing the transitive set of your dependencies. This file _must_ be produced by [req-compile](https://pypi.org/project/req-compile/) and include hashes and urls in the solution. This attribute is mutually exclusive with `requirements_locks`.   | <a href="https://bazel.build/concepts/labels">Label</a> | optional |  `None`  |
| <a id="py_requirements_repository-requirements_locks"></a>requirements_locks |  A map of fully resolved 'requirements.txt' pip requirement file containing the transitive set of your dependencies to labels of Bazel [platforms](https://bazel.build/extending/platforms). These requirements files __must__ be produced by [req-compile](https://pypi.org/project/req-compile/) and include hashes and urls in the solution. Each lock file provided will create a dependency tree matching `{name}_{id}__{package}` where `id` is the name of the lock file with `[".", "-"]` characters are replaced by `"_"` and the name `requirements` will be stripped. This means each `requirements_locks` entry will need to be somewhat uniquely named. This attribute is mutually exclusive with `requirements_lock`.   | <a href="https://bazel.build/rules/lib/dict">Dictionary: Label -> String</a> | optional |  `{}`  |


<a id="whl_repository"></a>

## whl_repository

<pre>
load("@rules_req_compile//:defs.bzl", "whl_repository")

whl_repository(<a href="#whl_repository-name">name</a>, <a href="#whl_repository-deps">deps</a>, <a href="#whl_repository-annotations">annotations</a>, <a href="#whl_repository-constraint">constraint</a>, <a href="#whl_repository-interpreter">interpreter</a>, <a href="#whl_repository-package">package</a>, <a href="#whl_repository-patches">patches</a>, <a href="#whl_repository-repo_mapping">repo_mapping</a>,
               <a href="#whl_repository-sdist_deps_repos">sdist_deps_repos</a>, <a href="#whl_repository-sha256">sha256</a>, <a href="#whl_repository-spoke_prefix">spoke_prefix</a>, <a href="#whl_repository-urls">urls</a>, <a href="#whl_repository-version">version</a>, <a href="#whl_repository-whl">whl</a>)
</pre>

A repository rule for extracting a python [wheel](https://peps.python.org/pep-0491/) and defining a `py_library`.

This repository is expected to be generated by [py_requirements_repository](#py_requirements_repository).

**ATTRIBUTES**


| Name  | Description | Type | Mandatory | Default |
| :------------- | :------------- | :------------- | :------------- | :------------- |
| <a id="whl_repository-name"></a>name |  A unique name for this repository.   | <a href="https://bazel.build/concepts/labels#target-names">Name</a> | required |  |
| <a id="whl_repository-deps"></a>deps |  A list of python package names that the current package depends on.   | List of strings | required |  |
| <a id="whl_repository-annotations"></a>annotations |  See [py_requirements_repository.annotation](#py_requirements_repository.annotation)   | String | optional |  `"{}"`  |
| <a id="whl_repository-constraint"></a>constraint |  An optional constraint to assign to `target_compatible_with` where all other configurations will be invalid.   | String | optional |  `""`  |
| <a id="whl_repository-interpreter"></a>interpreter |  Optional Python interpreter binary to use for building sdists.   | <a href="https://bazel.build/concepts/labels">Label</a> | optional |  `None`  |
| <a id="whl_repository-package"></a>package |  The name of the python package the wheel represents.   | String | required |  |
| <a id="whl_repository-patches"></a>patches |  Patches to apply to the installed wheel.   | <a href="https://bazel.build/concepts/labels">List of labels</a> | optional |  `[]`  |
| <a id="whl_repository-repo_mapping"></a>repo_mapping |  In `WORKSPACE` context only: a dictionary from local repository name to global repository name. This allows controls over workspace dependency resolution for dependencies of this repository.<br><br>For example, an entry `"@foo": "@bar"` declares that, for any time this repository depends on `@foo` (such as a dependency on `@foo//some:target`, it should actually resolve that dependency within globally-declared `@bar` (`@bar//some:target`).<br><br>This attribute is _not_ supported in `MODULE.bazel` context (when invoking a repository rule inside a module extension's implementation function).   | <a href="https://bazel.build/rules/lib/dict">Dictionary: String -> String</a> | optional |  |
| <a id="whl_repository-sdist_deps_repos"></a>sdist_deps_repos |  INTERNAL: DO NOT USE. Default dependencies for building source distributions.   | <a href="https://bazel.build/concepts/labels">List of labels</a> | optional |  `["@req_compile_sdist_compiler__pip//:pkg", "@req_compile_sdist_compiler__setuptools//:pkg", "@req_compile_sdist_compiler__wheel//:pkg"]`  |
| <a id="whl_repository-sha256"></a>sha256 |  The expected SHA-256 of the file downloaded.   | String | optional |  `""`  |
| <a id="whl_repository-spoke_prefix"></a>spoke_prefix |  The name of the [py_requirements_repository](#py_requirements_repository) plus a friendly platform suffix.   | String | required |  |
| <a id="whl_repository-urls"></a>urls |  A list of URLs to the python wheel.   | List of strings | optional |  `[]`  |
| <a id="whl_repository-version"></a>version |  The version of the python package.   | String | required |  |
| <a id="whl_repository-whl"></a>whl |  The label to a wheel.   | <a href="https://bazel.build/concepts/labels">Label</a> | optional |  `None`  |


