"""Read the step map of a frontend-slides deck.

The engine (upstream/frontend-slides-PKU) puts each slide in its own
`<section class="slide">` and reveals fragments with `class="st" data-st="N"`.
Slides are not nested. Step 0 is the arrival state, before any fragment.
ArrowRight then walks step 1..max, and the next press advances the slide.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SLIDE_TAG = re.compile(
    r"<(?P<tag>section|div)\b(?P<attrs>[^>]*)>",
    re.IGNORECASE,
)
_CLASS = re.compile(r"""class\s*=\s*["']([^"']*)["']""", re.IGNORECASE)
_DATA_ST = re.compile(r"""data-st\s*=\s*["'](\d+)["']""", re.IGNORECASE)
_TAG = re.compile(r"<[a-zA-Z][^>]*>")


@dataclass(frozen=True)
class Slide:
    number: int  # 1-based
    max_step: int


def _class_tokens(attrs: str) -> set[str]:
    match = _CLASS.search(attrs)
    if not match:
        return set()
    return set(match.group(1).split())


def _fragment_steps(fragment: str) -> list[int]:
    steps: list[int] = []
    for tag in _TAG.finditer(fragment):
        raw = tag.group(0)
        if "st" not in _class_tokens(raw):
            continue
        found = _DATA_ST.search(raw)
        if found:
            steps.append(int(found.group(1)))
    return steps


def parse_slides(html: str) -> list[Slide]:
    starts: list[int] = []
    for match in _SLIDE_TAG.finditer(html):
        if "slide" in _class_tokens(match.group("attrs")):
            starts.append(match.start())
    slides: list[Slide] = []
    for i, start in enumerate(starts):
        # Sections are not nested. Stop at </section> so a script after the
        # last slide cannot contribute a data-st that lives only in a string.
        close = html.lower().find("</section>", start)
        next_start = starts[i + 1] if i + 1 < len(starts) else len(html)
        if close != -1 and close < next_start:
            end = close
        else:
            end = next_start
        steps = _fragment_steps(html[start:end])
        slides.append(Slide(number=i + 1, max_step=max(steps, default=0)))
    if not slides:
        raise ValueError("no <section class=\"slide\"> (or div) found in the deck")
    return slides


def load_deck(path: Path) -> list[Slide]:
    return parse_slides(Path(path).read_text(encoding="utf-8"))


def walk_states(slides: list[Slide]) -> list[tuple[int, int]]:
    """Presentation order: for each slide, step 0 then 1..max_step."""
    states: list[tuple[int, int]] = []
    for slide in slides:
        for step in range(slide.max_step + 1):
            states.append((slide.number, step))
    return states


def resolve_deck_inputs(deck: Path, narration: Path | None) -> tuple[Path, Path]:
    """Accept a deck folder (deck.html + narration.yaml) or an HTML file."""
    deck = Path(deck)
    if deck.is_dir():
        html = deck / "deck.html"
        if not html.is_file():
            htmls = sorted(p for p in deck.glob("*.html") if p.is_file())
            if len(htmls) != 1:
                names = ", ".join(p.name for p in htmls) or "(none)"
                raise SystemExit(
                    f"{deck} needs deck.html, or exactly one html file (found {names})"
                )
            html = htmls[0]
        if narration is None:
            for name in ("narration.yaml", "narration.yml"):
                candidate = deck / name
                if candidate.is_file():
                    narration = candidate
                    break
            if narration is None:
                raise SystemExit(f"{deck} has no narration.yaml")
        return html.resolve(), Path(narration).resolve()

    if not deck.is_file():
        raise SystemExit(f"deck not found: {deck}")
    if narration is None:
        raise SystemExit("pass a deck folder, or --narration alongside an HTML file")
    return deck.resolve(), Path(narration).resolve()
