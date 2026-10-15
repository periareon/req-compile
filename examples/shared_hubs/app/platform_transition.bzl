"""A rule building a target for another platform, for the fallback lock test."""

def _platform_transition_impl(_settings, attr):
    return {"//command_line_option:platforms": str(attr.platform)}

_platform_transition = transition(
    implementation = _platform_transition_impl,
    inputs = [],
    outputs = ["//command_line_option:platforms"],
)

def _platform_transitioned_impl(ctx):
    return [DefaultInfo(files = ctx.attr.target[0][DefaultInfo].files)]

platform_transitioned = rule(
    doc = "Build `target` for `platform`.",
    implementation = _platform_transitioned_impl,
    attrs = {
        "platform": attr.label(
            doc = "The platform to build for.",
            mandatory = True,
        ),
        "target": attr.label(
            doc = "The target to build.",
            cfg = _platform_transition,
            mandatory = True,
        ),
        "_allowlist_function_transition": attr.label(
            default = "@bazel_tools//tools/allowlists/function_transition_allowlist",
        ),
    },
)
