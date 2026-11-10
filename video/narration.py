"""Narration script: one text block per slide step, the string that goes to TTS."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from checks.documents import Document, document_from_lines


@dataclass(frozen=True)
class Cue:
    slide: int  # 1-based, matching <!-- [Slide N] -->
    step: int   # 0 is the slide as it arrives, before any data-st reveal
    text: str


@dataclass(frozen=True)
class Script:
    title: str
    voice: str
    lang: str
    speed: float
    pad_seconds: float
    lexicon: Path | None
    steps: tuple[Cue, ...]
    path: Path


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def load_script(path: Path) -> Script:
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "steps" not in data:
        raise ValueError(f"{path}: expected a mapping with a steps list")
    raw_steps = data["steps"]
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError(f"{path}: steps must be a non-empty list")

    cues: list[Cue] = []
    seen: set[tuple[int, int]] = set()
    for i, item in enumerate(raw_steps, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: step {i} is not a mapping")
        try:
            slide = int(item["slide"])
            step = int(item["step"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{path}: step {i} needs integer slide and step") from exc
        if slide < 1 or step < 0:
            raise ValueError(f"{path}: step {i} has slide {slide} step {step}; slide starts at 1, step at 0")
        text = normalize_text(str(item.get("text", "")))
        if not text:
            raise ValueError(f"{path}: slide {slide} step {step} has empty text")
        key = (slide, step)
        if key in seen:
            raise ValueError(f"{path}: duplicate cue for slide {slide} step {step}")
        seen.add(key)
        cues.append(Cue(slide, step, text))

    lexicon = data.get("lexicon")
    lexicon_path = None
    if lexicon:
        lexicon_path = (path.parent / str(lexicon)).resolve()
        if not lexicon_path.is_file():
            raise ValueError(f"{path}: lexicon not found: {lexicon_path}")

    speed = float(data.get("speed", 1.0))
    if not 0.5 <= speed <= 2.0:
        raise ValueError(f"{path}: speed {speed} is outside the Kokoro range 0.5..2.0")
    pad = float(data.get("pad_seconds", 0.35))
    if pad < 0:
        raise ValueError(f"{path}: pad_seconds must be >= 0")

    return Script(
        title=str(data.get("title") or path.stem),
        voice=str(data.get("voice") or "af_sarah"),
        lang=str(data.get("lang") or "en-us"),
        speed=speed,
        pad_seconds=pad,
        lexicon=lexicon_path,
        steps=tuple(cues),
        path=path,
    )


def script_document(script: Script) -> Document:
    """Trace exactly the cue text parsed for captions and TTS."""
    return document_from_lines(
        script.path.resolve(),
        "narration",
        [cue.text for cue in script.steps],
    )

def check_against_deck(script: Script, states: list[tuple[int, int]]) -> None:
    """Require the narration to list exactly the deck's walk, in that order."""
    got = [(c.slide, c.step) for c in script.steps]
    if got == states:
        return
    missing = [s for s in states if s not in got]
    extra = [s for s in got if s not in states]
    lines = [f"Narration {script.path} does not match the deck walk."]
    if missing:
        lines.append("  missing: " + ", ".join(f"slide {s} step {t}" for s, t in missing))
    if extra:
        lines.append("  extra: " + ", ".join(f"slide {s} step {t}" for s, t in extra))
    if not missing and not extra:
        lines.append("  the cues are the right set but not in presentation order.")
    lines.append("  deck: " + ", ".join(f"{s}.{t}" for s, t in states))
    raise SystemExit("\n".join(lines))
