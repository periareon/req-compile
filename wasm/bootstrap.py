# Runs inside the embedded interpreter before anything else is imported.
#
# Installs an importer over the bundle the host linked into the module, so the
# unmodified req-compile sources and their dependencies import without a
# filesystem, then hands the input to the entry point and reports its output.
import _frozen_importlib as _bootstrap
import sys

import _host

_MAGIC = b"RQB1"


def _read_bundle(data):
    """Index the bundle: `RQB1`, then (u32 name length, name, u32 size, bytes)*."""
    if bytes(data[:4]) != _MAGIC:
        raise RuntimeError("bad bundle magic")
    files = {}
    offset = 4
    end = len(data)
    while offset < end:
        name_len = int.from_bytes(data[offset : offset + 4], "little")
        offset += 4
        name = bytes(data[offset : offset + name_len]).decode("utf-8")
        offset += name_len
        size = int.from_bytes(data[offset : offset + 4], "little")
        offset += 4
        files[name] = (offset, size)
        offset += size
    return files


class BundleFinder:
    """Import `.py` files straight from the bundle."""

    def __init__(self, data):
        self._data = data
        self._files = _read_bundle(data)

    def find_spec(self, name, path=None, target=None):
        base = name.replace(".", "/")
        for stem, is_package in ((base + "/__init__", True), (base, False)):
            for extension in (".pyc", ".py"):
                candidate = stem + extension
                if candidate in self._files:
                    spec = _bootstrap.ModuleSpec(
                        name, self, origin="/bundle/" + candidate, is_package=is_package
                    )
                    spec.has_location = True
                    if is_package:
                        spec.submodule_search_locations = ["/bundle/" + base]
                    return spec
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        origin = module.__spec__.origin
        offset, size = self._files[origin[len("/bundle/") :]]
        data = bytes(self._data[offset : offset + size])
        if origin.endswith(".pyc"):
            # Bytecode marshalled by `bundle.py --pyc` with a matching interpreter.
            import marshal

            module.__file__ = origin[: -len(".pyc")] + ".py"
            code = marshal.loads(data)
        else:
            module.__file__ = origin
            code = compile(data, origin, "exec", dont_inherit=True)
        exec(code, module.__dict__)

    def get_source(self, name):
        spec = self.find_spec(name)
        if spec is None or spec.origin.endswith(".pyc"):
            return None
        offset, size = self._files[spec.origin[len("/bundle/") :]]
        return bytes(self._data[offset : offset + size]).decode("utf-8")


# Executed during the core initialization phase, when only builtin and frozen
# modules import: put the bundle first so the main phase finds `encodings` in it.
sys.meta_path.insert(0, BundleFinder(_host.bundle()))


def run():
    """Executed once the interpreter is fully initialized."""
    from req_compile.wasm.entry import main

    output, code = main(bytes(_host.input()))
    _host.set_output(output, code)
