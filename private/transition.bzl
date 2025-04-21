"""Bazel rules for platform transitions"""

def _platform_transition_impl(_, attr):
    return {
        "//command_line_option:platforms": str(attr.platform),
    }

# Transition from any input configuration to one that includes the
# --platforms command-line flag.
_platform_transition = transition(
    implementation = _platform_transition_impl,
    inputs = [],
    outputs = [
        "//command_line_option:platforms",
    ],
)

def _platform_transitioned_file_impl(ctx):
    output_file = ctx.file.target

    providers = [DefaultInfo(
        files = depset([output_file]),
    )]

    if OutputGroupInfo in ctx.attr.target:
        providers.append(ctx.attr.target[OutputGroupInfo])

    return providers

platform_transitioned_file = rule(
    doc = "A rule for accessing files in a target's `OutputGroupInfo` through a transition.",
    implementation = _platform_transitioned_file_impl,
    cfg = _platform_transition,
    attrs = {
        "platform": attr.label(
            doc = "The label to a [Bazel platform](https://bazel.build/extending/platforms)",
        ),
        "target": attr.label(
            doc = "The target to transition.",
            allow_single_file = True,
            mandatory = True,
        ),
    },
)
