"""Lint narration, captions, and slide text for rules a machine can count.

The judgment stays in ``upstream/hep-skills``. This tool only applies the
fixed filler list and the word caps in ``config/language.yaml``:

- a banned phrase fails
- an HTML bullet over the word cap fails
- a narration sentence over the word cap is a warning, and a failure with
  ``--strict``

Run from the repository root::

    python3 -m checks.language scan PATH
    python3 -m checks.language scan PATH --strict
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from checks.documents import classify
from checks.yamlsubset import YamlError, load as load_yaml

_CONFIG = Path(__file__).resolve().parent / "config" / "language.yaml"
_SKIP_DIRS = {
    "upstream",
    "checks",
    "node_modules",
    ".git",
    "media",
    "build",
    ".venv",
    "venv",
    "__pycache__",
}
_HTML = {".html", ".htm"}
_CAPTION = {".srt", ".vtt"}
_NARRATION_SUFFIX = {".txt", ".md", ".markdown", ".yaml", ".yml", ".srt", ".vtt"}
_SENTENCE = re.compile(r"[^.!?]+[.!?]?")
_WORD = re.compile(r"[A-Za-z0-9]+(?:[-'/][A-Za-z0-9]+)*|[μχσ]|\d+")
_LI = re.compile(r"<li\b[^>]*>(.*?)</li>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_NARRATION_KEY = re.compile(r"(?m)^[ ]*narration:")


class LanguageConfigError(ValueError):
    """The phrase file cannot be read."""


@dataclass
class Phrase:
    id: str
    pattern: re.Pattern[str]


@dataclass
class Hit:
    severity: str
    rule_id: str
    path: str
    line: int
    detail: str


def load_config(path: Path | None = None) -> tuple[list[Phrase], int, int]:
    config_path = path or _CONFIG
    try:
        data = load_yaml(config_path.read_text(encoding="utf-8"))
    except (OSError, YamlError) as exc:
        raise LanguageConfigError(f"cannot read {config_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise LanguageConfigError("language config must be a mapping")
    phrases: list[Phrase] = []
    for entry in data.get("phrases") or []:
        if not isinstance(entry, dict) or "id" not in entry or "pattern" not in entry:
            raise LanguageConfigError(f"phrase entry needs id and pattern: {entry!r}")
        phrases.append(Phrase(str(entry["id"]), _phrase_pattern(str(entry["pattern"]))))
    bullet = int(data.get("bullet_word_limit") or 20)
    sentence = int(data.get("narration_sentence_word_limit") or 30)
    return phrases, bullet, sentence


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    parts = phrase.split()
    if not parts:
        raise LanguageConfigError("empty phrase")
    body = r"\s+".join(re.escape(part) for part in parts)
    return re.compile(rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])", re.IGNORECASE)


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def scan(root: Path, *, config: tuple[list[Phrase], int, int] | None = None) -> list[Hit]:
    phrases, bullet_limit, sentence_limit = config or load_config()
    hits: list[Hit] = []
    files = _files(root)
    for path in files:
        kind = _kind(path)
        if kind is None:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        visible = _TAG.sub(" ", text) if path.suffix.lower() in _HTML else text
        hits.extend(_phrases(visible, path, phrases))
        if path.suffix.lower() in _HTML:
            hits.extend(_bullets(text, path, bullet_limit))
        if kind == "narration":
            hits.extend(_sentences(visible, path, sentence_limit))
    return hits


def _files(root: Path) -> list[Path]:
    root = root.resolve()
    if root.is_file():
        return [root]
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_DIRS and not name.startswith(".")]
        for name in sorted(filenames):
            found.append(Path(dirpath) / name)
    return found


def _kind(path: Path) -> str | None:
    if path.name.startswith("."):
        return None
    suffix = path.suffix.lower()
    if "checks/config" in path.as_posix() or "checks/tests" in path.as_posix():
        return None
    classified = classify(path)
    if classified == "narration" and suffix in _NARRATION_SUFFIX:
        return "narration"
    if suffix in _HTML:
        return "slide"
    if suffix in _CAPTION:
        return "narration"
    if suffix in {".yaml", ".yml"}:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        if _NARRATION_KEY.search(text):
            return "narration"
    return None


def _phrases(text: str, path: Path, phrases: list[Phrase]) -> list[Hit]:
    hits: list[Hit] = []
    for phrase in phrases:
        for match in phrase.pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            hits.append(Hit(
                "fail",
                phrase.id,
                path.as_posix(),
                line,
                match.group(0),
            ))
    return hits


def _bullets(html: str, path: Path, limit: int) -> list[Hit]:
    hits: list[Hit] = []
    for match in _LI.finditer(html):
        plain = _TAG.sub(" ", match.group(1))
        count = len(words(plain))
        if count > limit:
            line = html.count("\n", 0, match.start()) + 1
            hits.append(Hit(
                "fail",
                "bullet_words",
                path.as_posix(),
                line,
                f"{count} words in a bullet (limit {limit})",
            ))
    return hits


def _sentences(text: str, path: Path, limit: int) -> list[Hit]:
    hits: list[Hit] = []
    for match in _SENTENCE.finditer(text):
        sentence = " ".join(match.group(0).split())
        if not sentence or sentence.startswith("#") or sentence.startswith("-"):
            continue
        count = len(words(sentence))
        if count > limit:
            line = text.count("\n", 0, match.start()) + 1
            hits.append(Hit(
                "warn",
                "narration_words",
                path.as_posix(),
                line,
                f"{count} words in a narration sentence (limit {limit})",
            ))
    return hits


def format_report(hits: list[Hit], *, strict: bool) -> str:
    failures = [hit for hit in hits if hit.severity == "fail" or (strict and hit.severity == "warn")]
    warnings = [hit for hit in hits if hit.severity == "warn" and not strict]
    lines = ["language lint: " + ("FAIL" if failures else "PASS")]
    for hit in hits:
        lines.append(f"  {hit.severity:4} {hit.rule_id:24} {hit.path}:{hit.line}  {hit.detail}")
    lines.append(f"{len(failures)} failure(s), {len(warnings)} warning(s)")
    return "\n".join(lines)


def ok(hits: list[Hit], *, strict: bool) -> bool:
    if any(hit.severity == "fail" for hit in hits):
        return False
    if strict and any(hit.severity == "warn" for hit in hits):
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m checks.language")
    sub = parser.add_subparsers(dest="command", required=True)
    scan_parser = sub.add_parser("scan", help="lint narration, captions, and HTML slides")
    scan_parser.add_argument("path", type=Path)
    scan_parser.add_argument("--strict", action="store_true", help="warnings fail too")
    args = parser.parse_args(argv)
    try:
        hits = scan(args.path)
    except LanguageConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(format_report(hits, strict=args.strict))
    return 0 if ok(hits, strict=args.strict) else 1


if __name__ == "__main__":
    raise SystemExit(main())
