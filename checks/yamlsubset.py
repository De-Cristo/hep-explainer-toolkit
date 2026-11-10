"""A small YAML subset loader.

The checks read marker lists and source manifests as YAML. This parser
covers that subset so the tools do not depend on PyYAML:

- indentation with spaces (tabs are an error)
- mappings and lists, including a list item that starts a mapping
- plain, single-quoted, and double-quoted scalars
- booleans ``true`` / ``false``, ``null`` / ``~``
- integers, decimals, and scientific notation (decimals stay ``Decimal``)
- one-line flow lists and mappings of scalars
- ``#`` comments

Anchors, tags, merge keys, and block scalars (``|``, ``>``) are rejected.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


class YamlError(ValueError):
    """The document is outside the subset this loader accepts."""

    def __init__(self, message: str, line: int | None = None) -> None:
        self.line = line
        if line is None:
            super().__init__(message)
        else:
            super().__init__(f"line {line}: {message}")


def load(text: str) -> Any:
    """Parse ``text`` and return a dict, list, or scalar."""
    lines = _physical_lines(text)
    if not lines:
        return None
    value, index = _parse_block(lines, 0, lines[0][0])
    if index != len(lines):
        raise YamlError("unexpected trailing content", lines[index][2])
    return value


def _physical_lines(text: str) -> list[tuple[int, str, int]]:
    prepared: list[tuple[int, str, int]] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw:
            raise YamlError("tabs are not allowed; indent with spaces", lineno)
        stripped = _strip_comment(raw)
        if stripped.strip() == "":
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        prepared.append((indent, stripped.strip(), lineno))
    return prepared


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(line):
        if in_double and char == "\\" and not escaped:
            escaped = True
            continue
        if char == "'" and not in_double and not escaped:
            in_single = not in_single
        elif char == '"' and not in_single and not escaped:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            return line[:index]
        escaped = False
    return line


def _parse_block(
    lines: list[tuple[int, str, int]], start: int, indent: int
) -> tuple[Any, int]:
    content = lines[start][1]
    if content.startswith("- ") or content == "-":
        return _parse_list(lines, start, indent)
    return _parse_map(lines, start, indent)


def _parse_map(
    lines: list[tuple[int, str, int]], start: int, indent: int
) -> tuple[dict[str, Any], int]:
    mapping: dict[str, Any] = {}
    index = start
    while index < len(lines):
        line_indent, content, lineno = lines[index]
        if line_indent < indent:
            break
        if line_indent != indent:
            raise YamlError("unexpected indent in a mapping", lineno)
        if content.startswith("- ") or content == "-":
            raise YamlError("expected a mapping entry, found a list item", lineno)
        key, rest = _split_key(content, lineno)
        if key in mapping:
            raise YamlError(f"duplicate key {key!r}", lineno)
        mapping[key], index = _parse_value(lines, index, indent, rest, lineno)
    if not mapping:
        raise YamlError("expected a mapping", lines[start][2])
    return mapping, index


def _parse_list(
    lines: list[tuple[int, str, int]], start: int, indent: int
) -> tuple[list[Any], int]:
    items: list[Any] = []
    index = start
    while index < len(lines):
        line_indent, content, lineno = lines[index]
        if line_indent < indent:
            break
        if line_indent != indent or not (content.startswith("- ") or content == "-"):
            break
        item_text = "" if content == "-" else content[2:].strip()
        if item_text == "":
            if index + 1 < len(lines) and lines[index + 1][0] > indent:
                value, index = _parse_block(lines, index + 1, lines[index + 1][0])
            else:
                value, index = None, index + 1
            items.append(value)
            continue
        key_split = _maybe_key(item_text)
        if key_split is None:
            items.append(_parse_scalar(item_text, lineno))
            index += 1
            continue
        # "- key: value" opens a mapping that continues at a deeper indent.
        item: dict[str, Any] = {}
        key, rest = key_split
        item[key], index = _parse_value(lines, index, indent, rest, lineno)
        while index < len(lines):
            next_indent, next_content, next_line = lines[index]
            if next_indent <= indent:
                break
            if next_content.startswith("- ") or next_content == "-":
                break
            next_key, next_rest = _split_key(next_content, next_line)
            if next_key in item:
                raise YamlError(f"duplicate key {next_key!r}", next_line)
            item[next_key], index = _parse_value(
                lines, index, next_indent, next_rest, next_line
            )
            # Further keys of this same mapping share next_indent. A deeper
            # indent belongs to the value just parsed, which consumed it.
            while (
                index < len(lines)
                and lines[index][0] > next_indent
                and not lines[index][1].startswith("-")
            ):
                # _parse_value should have consumed nested blocks. If anything
                # remains, it is a malformed sibling.
                raise YamlError("unexpected indent in a list item", lines[index][2])
        items.append(item)
    return items, index


def _parse_value(
    lines: list[tuple[int, str, int]],
    index: int,
    key_indent: int,
    rest: str,
    lineno: int,
) -> tuple[Any, int]:
    if rest in {"|", ">"}:
        raise YamlError(
            "block scalars are not supported; put the text in quotes", lineno
        )
    if rest != "":
        return _parse_scalar(rest, lineno), index + 1
    if index + 1 < len(lines) and lines[index + 1][0] > key_indent:
        return _parse_block(lines, index + 1, lines[index + 1][0])
    return None, index + 1


def _maybe_key(text: str) -> tuple[str, str] | None:
    try:
        key, rest = _split_key(text, None)
    except YamlError:
        return None
    if not _plain_key(key):
        return None
    return key, rest


def _plain_key(key: str) -> bool:
    if not key:
        return False
    first = key[0]
    if not (first.isalpha() or first == "_"):
        return False
    return all(char.isalnum() or char in "_-" for char in key)


def _split_key(text: str, lineno: int | None) -> tuple[str, str]:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(text):
        if in_double and char == "\\" and not escaped:
            escaped = True
            continue
        if char == "'" and not in_double and not escaped:
            in_single = not in_single
        elif char == '"' and not in_single and not escaped:
            in_double = not in_double
        elif char == ":" and not in_single and not in_double and not escaped:
            rest = text[index + 1 :]
            if rest == "" or rest.startswith(" "):
                key = _parse_key_token(text[:index].strip(), lineno)
                return key, rest.strip()
        escaped = False
    raise YamlError("expected 'key:'", lineno)


def _parse_key_token(token: str, lineno: int | None) -> str:
    if token == "":
        raise YamlError("missing key before ':'", lineno)
    if token[0] in {"'", '"'}:
        value = _parse_scalar(token, lineno if lineno is not None else 0)
        if not isinstance(value, str):
            raise YamlError("mapping keys must be strings", lineno)
        return value
    return token


def _parse_scalar(token: str, lineno: int) -> Any:
    if token == "":
        return None
    if token[0] == "[":
        return _parse_flow_list(token, lineno)
    if token[0] == "{":
        return _parse_flow_map(token, lineno)
    if token[0] == '"':
        return _parse_double(token, lineno)
    if token[0] == "'":
        return _parse_single(token, lineno)
    lowered = token.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "~"}:
        return None
    number = _parse_number(token)
    if number is not None:
        return number
    if token.startswith(("!", "&", "*")) or token in {"|", ">"}:
        raise YamlError(f"unsupported syntax {token!r}", lineno)
    return token


def _parse_number(token: str) -> int | Decimal | None:
    text = token
    if text[0] in {"+", "-"}:
        body = text[1:]
    else:
        body = text
    if body == "" or body[0] == ".":
        return None
    exponent = ""
    if "e" in body.lower():
        head, _, exponent = body.lower().partition("e")
        if exponent in {"", "+", "-"} or not _digits(exponent.lstrip("+-")):
            return None
        body = head
    if body.count(".") > 1:
        return None
    if "." in body:
        whole, frac = body.split(".", 1)
        if not _digits(whole) or not _digits(frac):
            return None
        if len(whole) > 1 and whole.startswith("0"):
            return None
        return Decimal(token)
    if not _digits(body):
        return None
    if len(body) > 1 and body.startswith("0") and exponent == "":
        return None
    if exponent != "" or "." in token:
        return Decimal(token)
    return int(token)


def _digits(text: str) -> bool:
    return text != "" and text.isdigit()


def _parse_double(token: str, lineno: int) -> str:
    if len(token) < 2 or token[-1] != '"':
        raise YamlError("unterminated double quote", lineno)
    chars: list[str] = []
    index = 1
    while index < len(token) - 1:
        char = token[index]
        if char == "\\":
            index += 1
            if index >= len(token) - 1:
                raise YamlError("bad escape in double-quoted string", lineno)
            escape = token[index]
            mapped = {
                "n": "\n",
                "t": "\t",
                "r": "\r",
                "\\": "\\",
                '"': '"',
                "/": "/",
            }.get(escape)
            if mapped is None:
                raise YamlError(f"unsupported escape \\{escape}", lineno)
            chars.append(mapped)
        else:
            chars.append(char)
        index += 1
    return "".join(chars)


def _parse_single(token: str, lineno: int) -> str:
    if len(token) < 2 or token[-1] != "'":
        raise YamlError("unterminated single quote", lineno)
    body = token[1:-1]
    if "'" in body.replace("''", ""):
        raise YamlError("unterminated single quote", lineno)
    return body.replace("''", "'")


def _parse_flow_list(token: str, lineno: int) -> list[Any]:
    inner = _flow_inner(token, "[", "]", lineno)
    if inner.strip() == "":
        return []
    return [_parse_scalar(part.strip(), lineno) for part in _split_flow(inner, lineno)]


def _parse_flow_map(token: str, lineno: int) -> dict[str, Any]:
    inner = _flow_inner(token, "{", "}", lineno)
    if inner.strip() == "":
        return {}
    mapping: dict[str, Any] = {}
    for part in _split_flow(inner, lineno):
        key, rest = _split_key(part.strip(), lineno)
        if rest == "":
            raise YamlError("flow mapping entry is missing a value", lineno)
        if key in mapping:
            raise YamlError(f"duplicate key {key!r}", lineno)
        mapping[key] = _parse_scalar(rest, lineno)
    return mapping


def _flow_inner(token: str, open_char: str, close_char: str, lineno: int) -> str:
    if not token.endswith(close_char):
        raise YamlError(f"unterminated flow collection {token!r}", lineno)
    depth = 0
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(token):
        if in_double and char == "\\" and not escaped:
            escaped = True
            continue
        if char == "'" and not in_double and not escaped:
            in_single = not in_single
        elif char == '"' and not in_single and not escaped:
            in_double = not in_double
        elif not in_single and not in_double:
            if char == open_char:
                depth += 1
            elif char == close_char:
                depth -= 1
                if depth == 0 and index != len(token) - 1:
                    raise YamlError(
                        "trailing characters after a flow collection", lineno
                    )
        escaped = False
    if depth != 0:
        raise YamlError(f"unterminated flow collection {token!r}", lineno)
    return token[1:-1]


def _split_flow(text: str, lineno: int) -> list[str]:
    parts: list[str] = []
    depth = 0
    in_single = False
    in_double = False
    escaped = False
    start = 0
    for index, char in enumerate(text):
        if in_double and char == "\\" and not escaped:
            escaped = True
            continue
        if char == "'" and not in_double and not escaped:
            in_single = not in_single
        elif char == '"' and not in_single and not escaped:
            in_double = not in_double
        elif not in_single and not in_double:
            if char in "[{":
                depth += 1
            elif char in "]}":
                depth -= 1
            elif char == "," and depth == 0:
                parts.append(text[start:index])
                start = index + 1
        escaped = False
    if in_single or in_double or depth != 0:
        raise YamlError("unterminated flow collection", lineno)
    tail = text[start:]
    if tail.strip() != "":
        parts.append(tail)
    return parts
