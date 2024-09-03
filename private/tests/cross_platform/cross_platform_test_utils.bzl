"""Bazel rules for testing cross-platform apabilities of req-compile repository rules"""

def _platform_transition_impl(_, attr):
    return {
        "//command_line_option:extra_toolchains": [str(extra) for extra in attr.extra_toolchains],
        "//command_line_option:platforms": str(attr.platform),
    }

# Transition from any input configuration to one that includes the
# --platforms command-line flag.
_platform_transition = transition(
    implementation = _platform_transition_impl,
    inputs = [],
    outputs = [
        "//command_line_option:platforms",
        "//command_line_option:extra_toolchains",
    ],
)

def _platform_transitioned_output_group_impl(ctx):
    target = ctx.attr.target
    outputs = getattr(target[OutputGroupInfo], ctx.attr.output_group)
    if not outputs:
        fail("Could not find output group '{}' in '{}'".format(ctx.attr.output_group, target.label))

    zip_file = outputs.to_list()[0]

    link = ctx.actions.declare_file("{}.{}".format(ctx.label.name, zip_file.extension).rstrip("."))
    ctx.actions.symlink(
        output = link,
        target_file = zip_file,
    )

    return [DefaultInfo(
        files = depset([link]),
    )]

platform_transitioned_output_group = rule(
    doc = "A rule for accessing files in a target's `OutputGroupInfo` through a transition.",
    implementation = _platform_transitioned_output_group_impl,
    cfg = _platform_transition,
    attrs = {
        "extra_toolchains": attr.label_list(
            doc = (
                "[extra_toolchains](https://bazel.build/reference/command-line-reference#flag--extra_toolchains) to " +
                "apply in the transition."
            ),
        ),
        "output_group": attr.string(
            doc = "The `OutputGroupInfo` field to access.",
            mandatory = True,
        ),
        "platform": attr.label(
            doc = "The label to a [Bazel platform](https://bazel.build/extending/platforms)",
        ),
        "target": attr.label(
            doc = "The target to transition.",
            mandatory = True,
        ),
    },
)

# fake values from https://bazel.build/tutorials/ccp-toolchain-config#configuring_the_c_toolchain
def _config_impl(ctx):
    return cc_common.create_cc_toolchain_config_info(
        ctx = ctx,
        toolchain_identifier = "req_compile_cross_platform_fake_cc_toolchain",
        host_system_name = "unknown",
        target_system_name = "unknown",
        target_cpu = "unknown",
        target_libc = "unknown",
        compiler = "unknown",
        abi_version = "unknown",
        abi_libc_version = "unknown",
    )

fake_cc_config = rule(
    implementation = _config_impl,
    attrs = {},
    provides = [CcToolchainConfigInfo],
)
