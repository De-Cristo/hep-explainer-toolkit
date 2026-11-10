"""Semantic cue mapping for frontend-slides decks.

The slide engine already uses .st[data-st=N] and ArrowRight to advance
fragments. This module adds stable semantic names without changing that
engine: a slide declares data-scene and reveal elements declare data-cue.
Narration and storyboard tools can then refer to scene/cue names while the
recorder still walks the engine's numeric slide/step states.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from checks.storyboard import StoryboardError, narration_segments
from checks.yamlsubset import YamlError, load as load_yaml


class CueMapError(ValueError):
    """Semantic slide cues are missing, ambiguous, or out of order."""


@dataclass(frozen=True)
class CueTarget:
    scene: str
    cue: str
    slide: int
    step: int


@dataclass(frozen=True)
class CueMap:
    deck: Path
    targets: dict[tuple[str, str], CueTarget]

    def resolve(self, scene: str, cue: str) -> tuple[int, int]:
        key = (scene, cue)
        try:
            target = self.targets[key]
        except KeyError as exc:
            raise CueMapError(
                f"{self.deck}: no slide target for scene={scene!r} cue={cue!r}"
            ) from exc
        return target.slide, target.step


class _DeckParser(HTMLParser):
    def __init__(self, path: Path) -> None:
        super().__init__(convert_charrefs=True)
        self.path = path
        self.slide_number = 0
        self.slide_stack: list[str | None] = []
        self.current_scene: str | None = None
        self.found: list[CueTarget] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attr = dict(attrs)
        classes = set(str(attr.get("class") or "").split())
        scene = None
        if "slide" in classes:
            self.slide_number += 1
            scene = str(attr.get("data-scene") or "").strip() or None
            self.current_scene = scene
        self.slide_stack.append(scene)

        raw_cues = str(attr.get("data-cue") or "").strip()
        if not raw_cues:
            return
        if self.current_scene is None:
            raise CueMapError(
                f"{self.path}: data-cue outside a slide with data-scene"
            )
        try:
            step = int(attr.get("data-st", "0"))
        except ValueError as exc:
            raise CueMapError(
                f"{self.path}: data-cue {raw_cues!r} has non-integer data-st"
            ) from exc
        if step < 0:
            raise CueMapError(f"{self.path}: cue step must be >= 0")
        for cue in raw_cues.replace(",", " ").split():
            self.found.append(
                CueTarget(self.current_scene, cue, self.slide_number, step)
            )

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.slide_stack:
            return
        popped = self.slide_stack.pop()
        if popped is not None:
            self.current_scene = next(
                (value for value in reversed(self.slide_stack) if value is not None),
                None,
            )


def load_cue_map(deck: Path) -> CueMap:
    deck = Path(deck).resolve()
    parser = _DeckParser(deck)
    try:
        parser.feed(deck.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CueMapError(f"cannot read {deck}: {exc}") from exc

    targets: dict[tuple[str, str], CueTarget] = {}
    for target in parser.found:
        key = (target.scene, target.cue)
        previous = targets.get(key)
        if previous and (previous.slide, previous.step) != (target.slide, target.step):
            raise CueMapError(
                f"{deck}: cue {target.scene}/{target.cue} maps to multiple steps"
            )
        targets[key] = target
    return CueMap(deck, targets)


def validate_scene_parity(scene_path: Path, deck_path: Path) -> list[str]:
    scene_path = Path(scene_path).resolve()
    try:
        document = load_yaml(scene_path.read_text(encoding="utf-8"))
    except (OSError, YamlError) as exc:
        raise CueMapError(f"cannot read {scene_path}: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("scenes"), list):
        raise CueMapError(f"{scene_path}: expected a scenes list")
    cue_map = load_cue_map(deck_path)
    rows: list[str] = []
    for raw_scene in document["scenes"]:
        if not isinstance(raw_scene, dict) or not raw_scene.get("id"):
            continue
        scene_id = str(raw_scene["id"])
        try:
            segments = narration_segments(raw_scene)
        except StoryboardError as exc:
            raise CueMapError(str(exc)) from exc
        semantic = [segment for segment in segments if segment.cue]
        if not semantic:
            continue
        positions: list[tuple[int, int]] = []
        for segment in semantic:
            slide, step = cue_map.resolve(scene_id, str(segment.cue))
            positions.append((slide, step))
            rows.append(
                f"{scene_id}/{segment.cue} -> slide {slide} step {step}"
            )
        if positions != sorted(positions):
            raise CueMapError(
                f"{scene_path}: cues for scene {scene_id} are not in presentation order"
            )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m slides.cues")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="validate scene cue parity with a live deck")
    check.add_argument("scene", type=Path)
    check.add_argument("deck", type=Path)
    manifest = sub.add_parser("manifest", help="emit semantic cue -> slide/step JSON")
    manifest.add_argument("deck", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "manifest":
            cue_map = load_cue_map(args.deck)
            payload = [
                {
                    "scene": target.scene,
                    "cue": target.cue,
                    "slide": target.slide,
                    "step": target.step,
                }
                for target in cue_map.targets.values()
            ]
            print(json.dumps(payload, indent=2))
            return 0
        rows = validate_scene_parity(args.scene, args.deck)
        print("slide cue parity: PASS")
        for row in rows:
            print("  " + row)
        return 0
    except CueMapError as exc:
        print(f"slide cue parity: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
