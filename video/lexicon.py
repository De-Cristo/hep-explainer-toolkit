"""HEP pronunciation replacements applied to narration before TTS.

Captions keep the author's spelling. Only the string sent to Kokoro is rewritten.
Rules are Python regular expressions. At each character the longest match wins,
so ``13.6 TeV`` is spoken as one unit and a later bare ``TeV`` rule does not
fire inside it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_LEXICON = Path(__file__).resolve().parent / "lexicon" / "hep.yaml"


@dataclass(frozen=True)
class Rule:
    pattern: re.Pattern[str]
    spoken: str
    source: str


def load_lexicon(path: Path | None = None) -> list[Rule]:
    path = Path(path) if path else DEFAULT_LEXICON
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_rules = data.get("rules", [])
    rules: list[Rule] = []
    for i, item in enumerate(raw_rules, start=1):
        try:
            pattern = item["pattern"]
            spoken = item["spoken"]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"{path}: rule {i} needs pattern and spoken") from exc
        flags = re.IGNORECASE if item.get("ignore_case", False) else 0
        try:
            compiled = re.compile(pattern, flags)
        except re.error as exc:
            raise ValueError(f"{path}: rule {i} is not a valid regex ({pattern!r}): {exc}") from exc
        rules.append(Rule(compiled, str(spoken), pattern))
    return rules


def apply_lexicon(text: str, rules: list[Rule]) -> str:
    """Rewrite ``text`` for speech. The original string is what captions show."""
    if not text:
        return text
    i = 0
    out: list[str] = []
    n = len(text)
    while i < n:
        best_end = i
        best_spoken: str | None = None
        for rule in rules:
            match = rule.pattern.match(text, i)
            if match and match.start() == i and match.end() > best_end:
                best_end = match.end()
                best_spoken = rule.spoken
        if best_spoken is not None:
            out.append(best_spoken)
            i = best_end
        else:
            out.append(text[i])
            i += 1
    return "".join(out)
