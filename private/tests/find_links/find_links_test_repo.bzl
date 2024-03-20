"""A repository rule for the req-compile find_links integration test."""

load("//private:whl_repo.bzl", "load_sdist_data")

def _find_links_test_repository_impl(repository_ctx):
    repository_ctx.file("WORKSPACE.bazel", """workspace(name = "{}")""".format(
        repository_ctx.name,
    ))

    content = repository_ctx.read(repository_ctx.path(repository_ctx.attr.build_file))
    repository_ctx.file("BUILD.bazel", content)

    wheel_data_path = repository_ctx.path(repository_ctx.attr.pyspark_wheel_data)
    wheel_data = load_sdist_data(repository_ctx, wheel_data_path)

    wheel = repository_ctx.path(str(wheel_data_path).replace(wheel_data_path.basename, wheel_data.wheel))
    repository_ctx.symlink(
        wheel,
        "{}/{}".format(repository_ctx.attr.wheeldir, wheel.basename),
    )

    reqs_in = repository_ctx.path(repository_ctx.attr.requirements_in)
    repository_ctx.symlink(
        reqs_in,
        reqs_in.basename,
    )

    # Because the wheel is being compiled on the fly in another repository rule
    # the sha256 value of it will not be expected to match what's committed to the
    # repo. To account for this, the checksum of the newly built wheel will be
    # embedded instead.
    reqs_txt = repository_ctx.path(repository_ctx.attr.requirements_txt)
    reqs_content = ""
    is_pyspark_hash = False
    for line in repository_ctx.read(reqs_txt).splitlines():
        if is_pyspark_hash:
            reqs_content += "    --hash=sha256:{}\n".format(wheel_data.sha256)
            is_pyspark_hash = False
            continue
        reqs_content += line + "\n"
        if line.startswith("pyspark=="):
            is_pyspark_hash = True

    repository_ctx.file(reqs_txt.basename, reqs_content)

find_links_test_repository = repository_rule(
    doc = "A repository rule for the req-compile find_links integration test.",
    implementation = _find_links_test_repository_impl,
    attrs = {
        "build_file": attr.label(
            doc = "The BUILD file to use for the repo.",
            allow_files = True,
            mandatory = True,
        ),
        "pyspark_wheel_data": attr.label(
            doc = "The path to a data file produced by `sdist_repository`.",
            allow_files = True,
            mandatory = True,
        ),
        "requirements_in": attr.label(
            doc = "The `requirements.in` file.",
            allow_files = True,
            mandatory = True,
        ),
        "requirements_txt": attr.label(
            doc = "The `requirements.txt` file.",
            allow_files = True,
            mandatory = True,
        ),
        "wheeldir": attr.string(
            doc = "The name of the wheeldir directory.",
            mandatory = True,
        ),
    },
)
