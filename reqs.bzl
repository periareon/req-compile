load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_file")  # a repo rule
load("//private:reqs_repo.bzl", "parse_lockfile")
load("//private:whl_repo.bzl", "whl_repository")

def _req_compile_impl(ctx):
    # collect artifacts from across the dependency graph
    artifacts = []

    input = ""
    repo_name = None
    for mod in ctx.modules:
        for req in mod.tags.requirement:
            print(req)
            input += req.name + "\n"

    print("compiling {}\n".format(input))
    ctx.file("REQUIREMENTS.in", input, executable=False)
    ctx.report_progress("Compiling requirements")
    result = ctx.execute(["req-compile", "REQUIREMENTS.in", "-i", "https://pypi.org/simple", "--urls", "--hashes"])

    parsed_lockfile = parse_lockfile(result.stdout, "", {}, "")
    for repo_name, data in parsed_lockfile.items():
        print(repo_name)
        whl_repository(
            name = repo_name,
            annotations = "{}",
            constraint = data["constraint"],
            deps = data["deps"],
            package = repo_name,
            sha256 = data["sha256"],
            urls = [data["url"]] if data.get("url", None) else None,
            version = data["version"],
            whl = data["whl"],
        )

_requirement = tag_class(attrs = {"name": attr.string(mandatory=True), "version": attr.string(), "extras": attr.string_list()})

req_compile = module_extension(
  implementation = _req_compile_impl,
  tag_classes = {"requirement": _requirement},
  os_dependent = True,
  arch_dependent = True,
)
