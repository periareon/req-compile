"""Patching modules and objects"""
import contextlib
import sys
import types
from typing import Any, Iterator, Optional, Tuple, Union

PatchToken = Tuple[types.ModuleType, str, Any]


def begin_patch(
    module: Union[str, types.ModuleType], member: str, new_value: Any
) -> Optional[PatchToken]:
    if isinstance(module, str):
        if module not in sys.modules:
            return None

        module = sys.modules[module]

    if not hasattr(module, member):
        old_member = None
    else:
        old_member = getattr(module, member)
    setattr(module, member, new_value)
    return module, member, old_member


def end_patch(token: Optional[PatchToken]) -> None:
    if token is None:
        return

    module, member, old_member = token
    if old_member is None:
        delattr(module, member)
    else:
        setattr(module, member, old_member)


@contextlib.contextmanager
def patch(*args: Any) -> Iterator:
    """Manager a patch in a contextmanager"""
    tokens = []
    for idx in range(0, len(args), 3):
        module, member, new_value = args[idx : idx + 3]
        tokens.append(begin_patch(module, member, new_value))

    try:
        yield
    finally:
        for token in tokens[::-1]:
            end_patch(token)
