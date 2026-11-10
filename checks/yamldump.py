"""Write data using the conservative YAML subset understood by checks.yamlsubset."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any


def dumps(value: Any) -> str:
    lines = _dump(value, 0)
    return "\n".join(lines) + "\n"


def _dump(value: Any, indent: int) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        if not value:
            return [prefix + "{}"]
        lines: list[str] = []
        for key, item in value.items():
            key_text = _key(str(key))
            if _is_scalar(item):
                lines.append(prefix + key_text + ": " + _scalar(item))
            else:
                lines.append(prefix + key_text + ":")
                lines.extend(_dump(item, indent + 2))
        return lines
    if isinstance(value, (list, tuple)):
        if not value:
            return [prefix + "[]"]
        lines = []
        for item in value:
            if _is_scalar(item):
                lines.append(prefix + "- " + _scalar(item))
            elif isinstance(item, dict) and item:
                iterator = iter(item.items())
                first_key, first_value = next(iterator)
                if _is_scalar(first_value):
                    lines.append(
                        prefix + "- " + _key(str(first_key)) + ": " + _scalar(first_value)
                    )
                else:
                    lines.append(prefix + "- " + _key(str(first_key)) + ":")
                    lines.extend(_dump(first_value, indent + 4))
                for key, child in iterator:
                    if _is_scalar(child):
                        lines.append(
                            " " * (indent + 2)
                            + _key(str(key))
                            + ": "
                            + _scalar(child)
                        )
                    else:
                        lines.append(" " * (indent + 2) + _key(str(key)) + ":")
                        lines.extend(_dump(child, indent + 4))
            else:
                lines.append(prefix + "-")
                lines.extend(_dump(item, indent + 2))
        return lines
    return [prefix + _scalar(value)]


def _is_scalar(value: Any) -> bool:
    if value in ([], (), {}):
        return True
    return value is None or isinstance(
        value, (str, int, float, Decimal, bool)
    )


def _key(value: str) -> str:
    if value and (value[0].isalpha() or value[0] == "_") and all(
        char.isalnum() or char in "_-" for char in value
    ):
        return value
    return json.dumps(value, ensure_ascii=False)


def _scalar(value: Any) -> str:
    if value in ([], ()):
        return "[]"
    if value == {}:
        return "{}"
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)
