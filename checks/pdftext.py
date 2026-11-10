"""Extract text from simple PDFs with the standard library.

Handles uncompressed streams and FlateDecode streams (``zlib``), and the
``Tj`` / ``TJ`` / ``'`` text operators with literal and hex strings. Custom
font encodings, Type0/CMap text, encrypted files, and image-only pages come
back empty. That gap is reported by the caller when a PDF yields no text.
"""

from __future__ import annotations

import re
import zlib


_STREAM = re.compile(rb"stream\r?\n(.*?)endstream", re.S)
_TJ = re.compile(r"\((?:\\.|[^\\)])*\)\s*Tj|\[(?:.|\n)*?\]\s*TJ|\((?:\\.|[^\\)])*\)\s*'", re.S)
_LITERAL = re.compile(r"\((?:\\.|[^\\)])*\)")
_HEX = re.compile(r"<([0-9A-Fa-f\s]+)>")


def extract_pdf_text(data: bytes) -> str:
    """Return text operators found in ``data``. Empty when none decode."""
    pieces: list[str] = []
    for match in _STREAM.finditer(data):
        header = data[max(0, match.start() - 400) : match.start()]
        raw = match.group(1)
        if raw.endswith(b"\r\n"):
            raw = raw[:-2]
        elif raw.endswith(b"\n"):
            raw = raw[:-1]
        if b"FlateDecode" in header:
            try:
                raw = zlib.decompress(raw)
            except zlib.error:
                continue
        pieces.append(_operators_to_text(raw))
    # Uncompressed literal strings sitting outside a decoded stream still
    # count: a hand-built one-page PDF often has a single content stream,
    # but some writers also leave a plain-text title in the info dictionary.
    if not any(piece.strip() for piece in pieces):
        pieces.append(_literals(data.decode("latin-1", errors="ignore")))
    return "\n".join(piece for piece in pieces if piece.strip())


def _operators_to_text(raw: bytes) -> str:
    text = raw.decode("latin-1", errors="ignore")
    chunks: list[str] = []
    for match in _TJ.finditer(text):
        chunk = _literals(match.group(0))
        if chunk:
            chunks.append(chunk)
    if chunks:
        return "\n".join(chunks)
    return _literals(text)


def _literals(text: str) -> str:
    parts: list[str] = []
    for match in _LITERAL.finditer(text):
        parts.append(_unescape_literal(match.group(0)[1:-1]))
    for match in _HEX.finditer(text):
        decoded = _unescape_hex(match.group(1))
        if decoded:
            parts.append(decoded)
    return "".join(parts)


def _unescape_literal(body: str) -> str:
    chars: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if char != "\\":
            chars.append(char)
            index += 1
            continue
        index += 1
        if index >= len(body):
            break
        escape = body[index]
        mapped = {
            "n": "\n",
            "r": "\r",
            "t": "\t",
            "b": "\b",
            "f": "\f",
            "(": "(",
            ")": ")",
            "\\": "\\",
        }.get(escape)
        if mapped is not None:
            chars.append(mapped)
            index += 1
            continue
        if escape in "\n\r":
            if escape == "\r" and index + 1 < len(body) and body[index + 1] == "\n":
                index += 1
            index += 1
            continue
        if escape.isdigit():
            octal = escape
            index += 1
            for _ in range(2):
                if index < len(body) and body[index].isdigit():
                    octal += body[index]
                    index += 1
                else:
                    break
            chars.append(chr(int(octal, 8) % 256))
            continue
        chars.append(escape)
        index += 1
    return "".join(chars)


def _unescape_hex(body: str) -> str:
    digits = "".join(body.split())
    if len(digits) % 2 == 1:
        digits += "0"
    try:
        raw = bytes.fromhex(digits)
    except ValueError:
        return ""
    if raw.startswith(b"\xfe\xff") and len(raw) % 2 == 0:
        return raw[2:].decode("utf-16-be", errors="ignore")
    return raw.decode("latin-1", errors="ignore")
