"""# Bazel rules for `req_compile`

## Setup

```python
load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

http_archive(
    name = "req_compile",
    sha256 = "{see_release}",
    urls = ["{see_release}"],
)

load("@rules_req_compile//:repositories.bzl", "req_compile_dependencies")

req_compile_dependencies()

load("@rules_req_compile//:repositories_transitive.bzl", "req_compile_transitive_dependencies")

req_compile_transitive_dependencies()
```

## Rules

- [py_reqs_compiler](#py_reqs_compiler)
- [py_reqs_solution_test](#py_reqs_solution_test)
- [py_requirements_repository](#py_requirements_repository)
- [sdist_repository](#sdist_repository)
- [whl_repository](#whl_repository)

---
---
"""

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
    "//private:sdist_repo.bzl",
    _sdist_repository = "sdist_repository",
)
load(
    "//private:whl_repo.bzl",
    _whl_repository = "whl_repository",
)

py_reqs_compiler = _py_reqs_compiler
py_reqs_solution_test = _py_reqs_solution_test
py_requirements_repository = _py_requirements_repository
sdist_repository = _sdist_repository
whl_repository = _whl_repository
