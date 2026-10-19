#!/usr/bin/env python3
"""Tidy the data segments of a module pre-initialized by Wizer.

Wizer keeps the original segments as empty passive placeholders (so that
segment indices stay valid) and adds up to ten thousand active segments holding
the snapshot. wasm-ld had already produced one active segment per data object,
tens of thousands of them. Runtimes cap the segment count (wasmtime at 100,000)
and pay per segment at instantiation, so this drops the empty placeholders,
which nothing references, and joins active segments separated by small gaps,
filling the gaps with the zeros they stood for.

Usage: merge_segments.py IN.wasm OUT.wasm [--gap BYTES]
"""

import argparse


def read_leb(data, pos):
    result = 0
    shift = 0
    while True:
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return result, pos


def leb(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def read_sleb(data, pos):
    """A signed LEB128, as `i32.const` takes its operand."""
    result = 0
    shift = 0
    while True:
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            if byte & 0x40:
                result -= 1 << shift
            return result, pos


def sleb(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        done = (value == 0 and not byte & 0x40) or (value == -1 and byte & 0x40)
        out.append(byte if done else byte | 0x80)
        if done:
            return bytes(out)


def read_offset(data, pos):
    """The operand of an `i32.const`, as the unsigned address it denotes."""
    value, pos = read_sleb(data, pos)
    return value & 0xFFFFFFFF, pos


def encode_offset(offset):
    return sleb(offset - (1 << 32) if offset >= 1 << 31 else offset)


def self_test():
    for value, encoded in [
        (0, b"\x00"),
        (63, b"\x3f"),
        (64, b"\xc0\x00"),
        (127, b"\xff\x00"),
        (128, b"\x80\x01"),
        (8192, b"\x80\xc0\x00"),
        ((1 << 31) - 1, b"\xff\xff\xff\xff\x07"),
        (1 << 31, b"\x80\x80\x80\x80\x78"),
        ((1 << 32) - 1, b"\x7f"),
    ]:
        assert encode_offset(value) == encoded, (value, encode_offset(value), encoded)
        decoded, end = read_offset(encoded, 0)
        assert (decoded, end) == (value, len(encoded)), (value, decoded)


def sections(data):
    if data[:8] != b"\0asm\x01\0\0\0":
        raise SystemExit("not a WebAssembly module")
    pos = 8
    while pos < len(data):
        section_id = data[pos]
        size, body_start = read_leb(data, pos + 1)
        yield section_id, data[body_start : body_start + size]
        pos = body_start + size


def parse_segments(body):
    """Active segments of memory 0 as (offset, bytes); empty passive ones are dropped."""
    count, pos = read_leb(body, 0)
    segments = []
    for _ in range(count):
        flags, pos = read_leb(body, pos)
        if flags == 2:
            memory, pos = read_leb(body, pos)
            if memory != 0:
                raise SystemExit("only memory 0 is supported")
        if flags in (0, 2):
            if body[pos] != 0x41:  # i32.const
                raise SystemExit("only constant offsets are supported")
            offset, pos = read_offset(body, pos + 1)
            if body[pos] != 0x0B:  # end
                raise SystemExit("unexpected offset expression")
            pos += 1
        size, pos = read_leb(body, pos)
        if flags == 1:
            if size:
                raise SystemExit("a non-empty passive segment cannot be dropped")
            continue
        segments.append((offset, body[pos : pos + size]))
        pos += size
    return count, segments


def merge(segments, gap):
    segments.sort(key=lambda item: item[0])
    merged = []
    for offset, data in segments:
        if merged:
            last_offset, last_data = merged[-1]
            end = last_offset + len(last_data)
            if offset - end <= gap:
                last_data.extend(b"\0" * (offset - end))
                last_data.extend(data)
                continue
        merged.append((offset, bytearray(data)))
    return merged


def encode_segments(segments):
    out = bytearray(leb(len(segments)))
    for offset, data in segments:
        out += b"\0\x41" + encode_offset(offset) + b"\x0b" + leb(len(data)) + data
    return bytes(out)


def main():
    self_test()
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument(
        "--gap", type=int, default=4096, help="largest zero gap to fill (bytes)"
    )
    args = parser.parse_args()

    with open(args.input, "rb") as handle:
        data = handle.read()

    parsed = [(section_id, body) for section_id, body in sections(data)]
    before = after = 0
    merged = None
    for section_id, body in parsed:
        if section_id == 11:
            before, segments = parse_segments(body)
            merged = merge(segments, args.gap)
            after = len(merged)

    out = bytearray(data[:8])
    for section_id, body in parsed:
        if section_id == 11 and merged is not None:
            body = encode_segments(merged)
        elif section_id == 12 and merged is not None:  # data count must agree
            body = leb(after)
        out += bytes([section_id]) + leb(len(body)) + body

    with open(args.output, "wb") as handle:
        handle.write(out)
    print(
        "data segments: {} -> {} (gaps up to {} bytes filled), {} -> {} bytes".format(
            before, after, args.gap, len(data), len(out)
        )
    )


if __name__ == "__main__":
    main()
