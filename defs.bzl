"""# Bazel rules for `rules_req_compile`

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
"""

load(
    "//private:annotation.bzl",
    _py_package_annotation = "py_package_annotation",
    _py_package_annotation_consumer = "py_package_annotation_consumer",
    _py_package_annotation_target = "py_package_annotation_target",
)
load(
    "//private:compiler.bzl",
    _py_reqs_compiler = "py_reqs_compiler",
    _py_reqs_solution_test = "py_reqs_solution_test",
)
load(
    "//private:reqs_repo.bzl",
    _py_requirements_repository = "py_requirements_repository",
)
load(
    "//private:whl_repo.bzl",
    _whl_repository = "whl_repository",
)

py_package_annotation = _py_package_annotation
py_package_annotation_consumer = _py_package_annotation_consumer
py_package_annotation_target = _py_package_annotation_target
py_reqs_compiler = _py_reqs_compiler
py_reqs_solution_test = _py_reqs_solution_test
py_requirements_repository = _py_requirements_repository
whl_repository = _whl_repository
