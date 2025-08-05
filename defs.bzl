"""# Bazel rules for `rules_req_compile`

- [py_package_annotation_consumer](#py_package_annotation_consumer)
- [py_package_annotation_target](#py_package_annotation_target)
- [py_package_annotation](#py_package_annotation)
- [py_reqs_compiler](#py_reqs_compiler)
- [py_reqs_remote_compiler](#py_reqs_remote_compiler)
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
    "//private:remote_compiler.bzl",
    _py_reqs_remote_compiler = "py_reqs_remote_compiler",
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
py_reqs_remote_compiler = _py_reqs_remote_compiler
py_reqs_solution_test = _py_reqs_solution_test
py_requirements_repository = _py_requirements_repository
whl_repository = _whl_repository
