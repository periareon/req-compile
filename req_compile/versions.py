from typing import Tuple

import pkg_resources
from packaging.version import Version
from pkg_resources import Requirement

from req_compile.utils import parse_version

PART_MAX = "999999999"


def _offset_minor_version(version: Version, offset: int, pos: int = 2) -> Version:
    parts = str(version).split(".")

    for idx, part in enumerate(parts):
        for char_idx, char in enumerate(part):
            if not char.isdigit():
                # If the entire thing starts with a character, drop it
                # because it's a suffix
                if char_idx == 0:
                    parts = parts[:idx]
                    break
                parts[idx] = str(int(part[:char_idx]))
                break

    while len(parts) < 3:
        parts += ["0"]

    cur_version = int(parts[pos])
    if cur_version == 0 and offset < 0:
        if pos == 0:
            raise ValueError("Cannot create a version less than 0")
        parts[pos] = PART_MAX
        return _offset_minor_version(parse_version(".".join(parts)), -1, pos=pos - 1)
    parts[pos] = str(int(parts[pos]) + offset)
    return parse_version(".".join(parts))


def _build_wildcard_min_max(version: str) -> Tuple[Version, Version]:
    pre_wildcard_portion, _, _ = version.partition("*")
    if pre_wildcard_portion[-1] != ".":
        pre_wildcard_portion += "."
    return parse_version(pre_wildcard_portion + "0"), parse_version(
        pre_wildcard_portion + PART_MAX
    )


def is_possible(
    req: pkg_resources.Requirement,
) -> bool:  # pylint: disable=too-many-branches
    """Determine whether the requirement with its given specifiers is even possible.

    Args:
        req: Requirement to check.

    Returns:
        Whether the constraint can be satisfied.
    """
    lower_bound = parse_version("0.0.0")

    # The current exact match, as seen in a == specifier.
    exact = None

    # Collection of "!=" specifier versions. We can't see an exact match
    # the is equal to any of these.
    not_equal = []

    upper_bound = parse_version("{max}.{max}.{max}".format(max=PART_MAX))
    if len(req.specifier) == 1:  # type: ignore[attr-defined]
        return True

    for spec in req.specifier:  # type: ignore[attr-defined]
        # Special block just for ==, since it may refer to wildcard versions
        # which are not parseable as a packaging.version Version.
        if spec.operator in "==":
            # Is it a wild card version? That actually means a range.
            if "*" in spec.version:
                possible_new_lower, new_possible_upper = _build_wildcard_min_max(
                    spec.version
                )
                if possible_new_lower > lower_bound:
                    lower_bound = possible_new_lower
                if new_possible_upper < upper_bound:
                    upper_bound = new_possible_upper
            else:
                if exact is None:
                    exact = parse_version(spec.version)
                # Cannot have two == specifies with different versions.
                elif exact != parse_version(spec.version):
                    return False
            continue

        if spec.operator == "!=":
            if "*" in spec.version:
                # With != wildcards, we have our only "OR" condition in a requirement
                # expression. Try both branches along with all other specs.
                # This effectively transforms the first wildcard expression into 2
                # new requirements:
                #   project >=2, <4, !=4.2.*
                # becomes
                #   project >=2, <4, <4.2.0
                #   project >=2, <4, >4.2.MAX
                all_specs = list(req.specifier)
                all_specs.remove(spec)
                new_specs = ",".join(str(spec) for spec in all_specs)

                spec_lower, spec_upper = _build_wildcard_min_max(spec.version)
                req_upper = Requirement.parse(
                    req.project_name + new_specs + ",>{}".format(spec_upper)
                )
                req_lower = Requirement.parse(
                    req.project_name + new_specs + ",<{}".format(spec_lower)
                )
                return is_possible(req_lower) or is_possible(req_upper)
            else:
                not_equal.append(parse_version(spec.version))
            continue

        parsed_version = parse_version(spec.version)
        if spec.operator == ">":
            if parsed_version > lower_bound:
                lower_bound = _offset_minor_version(parsed_version, 1)
        elif spec.operator == ">=":
            if parsed_version >= lower_bound:
                lower_bound = parsed_version
        elif spec.operator == "<":
            if parsed_version < upper_bound:
                upper_bound = _offset_minor_version(parsed_version, -1)
        elif spec.operator == "<=":
            if parsed_version <= upper_bound:
                upper_bound = parsed_version
    # Some kind of parsing error occurred
    if upper_bound is None or lower_bound is None:
        return True

    # No possible versions.
    if upper_bound < lower_bound:
        return False

    if exact is not None:
        return exact in req  # type: ignore[operator]

    for check in not_equal:
        if check == exact:
            return False
    return True
