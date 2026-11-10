"""Read cheap image metadata. No pixel decoding and no OCR.

PNG tEXt / zTXt / iTXt chunks, JPEG COM segments, and GIF comment
extensions are plain enough to inspect with ``zlib`` and ``struct``.
EXIF blobs are scanned as ASCII / UTF-16 strings when they are short.
"""

from __future__ import annotations

import struct
import zlib


def metadata_strings(data: bytes, kind: str) -> list[tuple[str, str]]:
    """Return ``(channel, text)`` pairs found in ``data``.

    ``kind`` is a lowercase extension without the dot (``png``, ``jpg``,
    ``jpeg``, ``gif``, ``webp``). Unknown kinds return whatever long
    printable runs sit in the first 64 KiB.
    """
    if kind == "png":
        return _png(data)
    if kind in {"jpg", "jpeg"}:
        return _jpeg(data)
    if kind == "gif":
        return _gif(data)
    if kind == "webp":
        return _strings(data[:65536], "webp")
    return []


def _png(data: bytes) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return found
    offset = 8
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        tag = data[offset + 4 : offset + 8]
        start = offset + 8
        end = start + length
        if end + 4 > len(data) or length > 8_000_000:
            break
        chunk = data[start:end]
        if tag == b"tEXt":
            keyword, _, text = chunk.partition(b"\x00")
            found.append((_channel("png:tEXt", keyword), _decode(text)))
        elif tag == b"zTXt" and b"\x00" in chunk:
            keyword, _, rest = chunk.partition(b"\x00")
            if rest[:1] == b"\x00":
                try:
                    text = zlib.decompress(rest[1:])
                except zlib.error:
                    text = b""
                found.append((_channel("png:zTXt", keyword), _decode(text)))
        elif tag == b"iTXt" and b"\x00" in chunk:
            keyword, _, rest = chunk.partition(b"\x00")
            found.append((_channel("png:iTXt", keyword), _decode(rest)))
        offset = end + 4
        if tag == b"IEND":
            break
    return [(channel, text) for channel, text in found if text.strip()]


def _jpeg(data: bytes) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if not data.startswith(b"\xff\xd8"):
        return found
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        if marker in {0xD8, 0xD9}:
            break
        if marker == 0xDA:  # start of scan: entropy-coded data follows
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            offset += 2
            continue
        if offset + 4 > len(data):
            break
        length = struct.unpack(">H", data[offset + 2 : offset + 4])[0]
        payload = data[offset + 4 : offset + 2 + length]
        if marker == 0xFE:
            found.append(("jpeg:COM", _decode(payload)))
        elif marker in {0xE1, 0xE2, 0xED}:
            found.extend(_strings(payload[:65536], f"jpeg:APP{marker - 0xE0}"))
        offset += 2 + length
    return [(channel, text) for channel, text in found if text.strip()]


def _gif(data: bytes) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if not data.startswith((b"GIF87a", b"GIF89a")):
        return found
    offset = 0
    while True:
        index = data.find(b"\x21\xfe", offset)
        if index < 0 or index + 2 >= len(data):
            break
        cursor = index + 2
        parts: list[bytes] = []
        while cursor < len(data):
            size = data[cursor]
            cursor += 1
            if size == 0:
                break
            parts.append(data[cursor : cursor + size])
            cursor += size
        text = _decode(b"".join(parts))
        if text.strip():
            found.append(("gif:comment", text))
        offset = cursor
    return found


def _strings(data: bytes, channel: str) -> list[tuple[str, str]]:
    runs: list[str] = []
    current: list[str] = []
    for byte in data:
        if 32 <= byte < 127 or byte in {9, 10, 13}:
            current.append(chr(byte))
        else:
            if len(current) >= 6:
                runs.append("".join(current))
            current = []
    if len(current) >= 6:
        runs.append("".join(current))
    # UTF-16LE ASCII, common in EXIF descriptions.
    if len(data) >= 8:
        wide: list[str] = []
        pairs = data[:65536]
        index = 0
        while index + 1 < len(pairs):
            if pairs[index + 1] == 0 and 32 <= pairs[index] < 127:
                wide.append(chr(pairs[index]))
                index += 2
            else:
                if len(wide) >= 6:
                    runs.append("".join(wide))
                wide = []
                index += 1
        if len(wide) >= 6:
            runs.append("".join(wide))
    text = "\n".join(runs)
    if not text.strip():
        return []
    return [(channel, text)]


def _channel(prefix: str, keyword: bytes) -> str:
    name = keyword.decode("latin-1", errors="replace").strip() or "text"
    return f"{prefix}:{name}"


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ""
