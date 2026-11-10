#!/usr/bin/env python3
"""Write one deterministic toy artifact.

The provenance check reruns this script and compares a sha256. It only
emits files whose names it knows. Nothing here is a CMS result.

Usage: python3 examples/toy/emit.py OUTPUT
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path


def toy_png() -> bytes:
    """1x1 PNG whose comment says it is a toy simulation."""
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    text = b"Comment\x00TOY simulated plot"
    raw = zlib.compress(b"\x00\xff\x00\x00")

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    return (
        signature
        + chunk(b"IHDR", ihdr)
        + chunk(b"tEXt", text)
        + chunk(b"IDAT", raw)
        + chunk(b"IEND", b"")
    )


def _stored(name: str) -> bytes:
    """Bytes of a hand-authored toy file, compressed beside this script.

    The provenance check reruns this script and compares the hash to the
    copy under video/examples/toy-peak. Editing that copy without
    refreshing the payload fails the check.
    """
    blob = Path(__file__).resolve().parent / "payloads" / f"{name}.zz"
    return zlib.decompress(blob.read_bytes())


_ARTIFACTS = {
    "toy_plot.png": toy_png,
    "deck.html": lambda: _stored("deck.html"),
    "narration.yaml": lambda: _stored("narration.yaml"),
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: emit.py OUTPUT", file=sys.stderr)
        return 2
    dest = Path(args[0])
    builder = _ARTIFACTS.get(dest.name)
    if builder is None:
        print(f"unknown toy artifact {dest.name}", file=sys.stderr)
        return 2
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(builder())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
