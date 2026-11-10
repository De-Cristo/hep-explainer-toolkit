"""Validate the authoring brief that comes before slides or scene YAML.

The brief captures pedagogical decisions that should not be hidden inside
narration: who the explanation is for, what they already know, what they
must learn, and which scientific distinctions must survive simplification.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from checks.yamlsubset import YamlError, load as load_yaml

_MEDIA = {"slides", "video", "figure", "web", "talk"}
_REQUIRED_TOP = {"topic", "audience", "purpose", "medium", "learning_goal"}


class BriefError(ValueError):
    """The authoring brief is incomplete or malformed."""


@dataclass(frozen=True)
class Brief:
    path: Path
    topic: str
    audience_profile: str
    knows: tuple[str, ...]
    introduce: tuple[str, ...]
    purpose: str
    medium: str
    learning_goal: str
    duration_minutes: float | None
    required_distinctions: tuple[str, ...]
    avoid: tuple[str, ...]


def load_brief(path: Path) -> Brief:
    path = Path(path)
    try:
        data = load_yaml(path.read_text(encoding="utf-8"))
    except (OSError, YamlError) as exc:
        raise BriefError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise BriefError(f"{path} must be a mapping")

    missing = sorted(key for key in _REQUIRED_TOP if not data.get(key))
    if missing:
        raise BriefError("missing required field(s): " + ", ".join(missing))

    audience = data.get("audience")
    if not isinstance(audience, dict) or not _text(audience.get("profile")):
        raise BriefError("audience.profile is required")

    knows = _string_list(audience.get("knows"), "audience.knows")
    introduce = _string_list(audience.get("introduce"), "audience.introduce")
    distinctions = _string_list(
        data.get("required_distinctions"), "required_distinctions"
    )
    avoid = _string_list(data.get("avoid"), "avoid")

    medium = _text(data.get("medium"))
    if medium not in _MEDIA:
        raise BriefError(
            f"medium must be one of {', '.join(sorted(_MEDIA))}; got {medium!r}"
        )

    duration = data.get("duration_minutes")
    duration_value: float | None = None
    if duration is not None:
        if not isinstance(duration, (int, Decimal)):
            raise BriefError("duration_minutes must be a positive number")
        duration_value = float(duration)
        if duration_value <= 0:
            raise BriefError("duration_minutes must be > 0")

    return Brief(
        path=path,
        topic=_text(data["topic"]),
        audience_profile=_text(audience["profile"]),
        knows=knows,
        introduce=introduce,
        purpose=_text(data["purpose"]),
        medium=medium,
        learning_goal=_text(data["learning_goal"]),
        duration_minutes=duration_value,
        required_distinctions=distinctions,
        avoid=avoid,
    )


def format_brief(brief: Brief) -> str:
    lines = [
        "authoring brief: PASS",
        f"  topic: {brief.topic}",
        f"  audience: {brief.audience_profile}",
        f"  purpose: {brief.purpose}",
        f"  medium: {brief.medium}",
        f"  learning goal: {brief.learning_goal}",
    ]
    if brief.duration_minutes is not None:
        lines.append(f"  duration: {brief.duration_minutes:g} min")
    lines.append(f"  prior concepts: {len(brief.knows)}")
    lines.append(f"  concepts to introduce: {len(brief.introduce)}")
    lines.append(f"  required distinctions: {len(brief.required_distinctions)}")
    lines.append(f"  avoid items: {len(brief.avoid)}")
    return "\n".join(lines)


def _text(value: object) -> str:
    return str(value or "").strip()


def _string_list(value: object, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise BriefError(f"{name} must be a list")
    result = tuple(_text(item) for item in value)
    if any(not item for item in result):
        raise BriefError(f"{name} contains an empty item")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m checks.brief")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="validate an authoring brief")
    check.add_argument("brief", type=Path)
    args = parser.parse_args(argv)
    try:
        brief = load_brief(args.brief)
    except BriefError as exc:
        print(f"authoring brief: FAIL: {exc}", file=sys.stderr)
        return 1
    print(format_brief(brief))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
