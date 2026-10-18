#!/usr/bin/env python3
"""Call the solver module the way Bazel's `execute_wasm` does, for development.

Usage: run_local.py MODULE.wasm < input.json

Instantiates the module with no imports, calls `_initialize`, places the input
with `allocate`, calls `solve(input_ptr, input_len, output_ptr_ptr, output_len_ptr)`
and prints the output buffer. The return code of the call is the exit status.
"""

import sys
import time

import wasmtime


def execute(
    path: str, function: str, data: bytes, memory_limit: int = 1 << 30
) -> tuple:
    config = wasmtime.Config()
    config.cranelift_opt_level = "speed"
    engine = wasmtime.Engine(config)
    started = time.monotonic()
    module = wasmtime.Module.from_file(engine, path)
    compiled = time.monotonic()
    store = wasmtime.Store(engine)
    store.set_limits(memory_size=memory_limit)
    instance = wasmtime.Instance(store, module, [])
    exports = instance.exports(store)
    if "_initialize" in exports:  # absent after Wizer pre-initialization
        exports["_initialize"](store)
    memory = exports["memory"]
    allocate = exports["allocate"]

    input_ptr = allocate(store, len(data), 1)
    memory.write(store, data, input_ptr)
    out_ptr_ptr = allocate(store, 4, 4)
    out_len_ptr = allocate(store, 4, 4)
    memory.write(store, b"\0" * 4, out_ptr_ptr)
    memory.write(store, b"\0" * 4, out_len_ptr)

    code = exports[function](store, input_ptr, len(data), out_ptr_ptr, out_len_ptr)
    out_ptr = int.from_bytes(memory.read(store, out_ptr_ptr, out_ptr_ptr + 4), "little")
    out_len = int.from_bytes(memory.read(store, out_len_ptr, out_len_ptr + 4), "little")
    output = bytes(memory.read(store, out_ptr, out_ptr + out_len))
    finished = time.monotonic()
    print(
        f"[run_local] compile {compiled - started:.2f}s, call {finished - compiled:.2f}s, "
        f"memory {memory.data_len(store) >> 20} MiB",
        file=sys.stderr,
    )
    return code, output


def main() -> None:
    code, output = execute(
        sys.argv[1],
        sys.argv[2] if len(sys.argv) > 2 else "solve",
        sys.stdin.buffer.read(),
    )
    sys.stdout.buffer.write(output)
    sys.stdout.buffer.write(b"\n")
    sys.exit(code)


if __name__ == "__main__":
    main()
