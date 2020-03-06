"""Patching modules and objects"""
import contextlib
import sys


def begin_patch(module, member, new_value):
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


def end_patch(token):
    if token is None:
        return

    module, member, old_member = token
    if old_member is None:
        delattr(module, member)
    else:
        setattr(module, member, old_member)


@contextlib.contextmanager
def patch(*args):
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
