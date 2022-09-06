import packaging.version
import pkg_resources

from req_compile.utils import parse_version

PART_MAX = "999999999"


def _offset_minor_version(
    version: packaging.version.Version, offset: int, pos: int = 2
) -> packaging.version.Version:
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


def is_possible(
    req: pkg_resources.Requirement,
) -> bool:  # pylint: disable=too-many-branches
    """Determine whether the requirement with its given specifiers is even possible.

    Args:
        req: Requirement to check.

    Returns:
        Whether the constraint can be satisfied.
    """
    lower_bound = pkg_resources.parse_version("0.0.0")
    exact = None
    not_equal = []
    upper_bound = pkg_resources.parse_version("{max}.{max}.{max}".format(max=PART_MAX))
    if len(req.specifier) == 1:  # type: ignore[attr-defined]
        return True

    for spec in req.specifier:  # type: ignore[attr-defined]
        version = parse_version(spec.version)
        if spec.operator == "==":
            if exact is None:
                exact = version
            if exact != version:
                return False
        if spec.operator == "!=":
            not_equal.append(version)
        elif spec.operator == ">":
            if version > lower_bound:
                lower_bound = _offset_minor_version(version, 1)
        elif spec.operator == ">=":
            if version >= lower_bound:
                lower_bound = version
        elif spec.operator == "<":
            if version < upper_bound:
                upper_bound = _offset_minor_version(version, -1)
        elif spec.operator == "<=":
            if version <= upper_bound:
                upper_bound = version
    # Some kind of parsing error occurred
    if upper_bound is None or lower_bound is None:
        return True
    if upper_bound < lower_bound:
        return False
    if exact is not None:
        if exact > upper_bound or exact < lower_bound:
            return False
    for check in not_equal:
        if check == exact:
            return False
    return True
