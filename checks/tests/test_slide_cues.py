"""Semantic cue parity between scene storyboards and frontend slide steps."""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from slides.cues import CueMapError, load_cue_map, validate_scene_parity


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class SlideCueTest(unittest.TestCase):
    def test_deck_maps_semantic_cues_to_numeric_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            deck = _write(
                folder / "deck.html",
                """<section class="slide" data-scene="wh">
<div class="st" data-st="1" data-cue="incoming">incoming</div>
<div class="st" data-st="2" data-cue="complete">complete</div>
</section>
<section class="slide" data-scene="zh">
<div class="st" data-st="1" data-cue="incoming">incoming</div>
</section>
""",
            )
            cue_map = load_cue_map(deck)
        self.assertEqual(cue_map.resolve("wh", "incoming"), (1, 1))
        self.assertEqual(cue_map.resolve("wh", "complete"), (1, 2))
        self.assertEqual(cue_map.resolve("zh", "incoming"), (2, 1))

    def test_scene_and_deck_cue_order_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            deck = _write(
                folder / "deck.html",
                """<section class="slide" data-scene="demo">
<div class="st" data-st="1" data-cue="first">first</div>
<div class="st" data-st="2" data-cue="second">second</div>
</section>
""",
            )
            scene = _write(
                folder / "scene.yaml",
                textwrap.dedent(
                    """
                    title: demo
                    scenes:
                      - id: demo
                        narration:
                          - cue: first
                            text: "First statement."
                          - cue: second
                            text: "Second statement."
                        visual:
                          kind: slide
                        claims: []
                    """
                ),
            )
            rows = validate_scene_parity(scene, deck)
        self.assertEqual(
            rows,
            [
                "demo/first -> slide 1 step 1",
                "demo/second -> slide 1 step 2",
            ],
        )

    def test_missing_live_cue_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            deck = _write(
                folder / "deck.html",
                """<section class="slide" data-scene="demo">
<div class="st" data-st="1" data-cue="first">first</div>
</section>
""",
            )
            scene = _write(
                folder / "scene.yaml",
                textwrap.dedent(
                    """
                    title: demo
                    scenes:
                      - id: demo
                        narration:
                          - cue: missing
                            text: "This cue has no live reveal."
                        visual:
                          kind: slide
                        claims: []
                    """
                ),
            )
            with self.assertRaises(CueMapError):
                validate_scene_parity(scene, deck)

    def test_one_semantic_cue_cannot_point_to_two_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            deck = _write(
                Path(tmp) / "deck.html",
                """<section class="slide" data-scene="demo">
<div class="st" data-st="1" data-cue="same">one</div>
<div class="st" data-st="2" data-cue="same">two</div>
</section>
""",
            )
            with self.assertRaises(CueMapError):
                load_cue_map(deck)


if __name__ == "__main__":
    unittest.main()
