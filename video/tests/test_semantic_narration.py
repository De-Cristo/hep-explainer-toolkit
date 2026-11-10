"""Semantic narration can address live slide cues instead of numeric steps."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from slides.cues import load_cue_map
from video.narration import load_script


class SemanticNarrationTest(unittest.TestCase):
    def test_scene_cue_resolves_to_slide_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            deck = folder / "deck.html"
            deck.write_text(
                """<section class="slide" data-scene="demo">
<div class="st" data-st="1" data-cue="reveal">result</div>
</section>
""",
                encoding="utf-8",
            )
            narration = folder / "narration.yaml"
            narration.write_text(
                """steps:
  - scene: demo
    cue: reveal
    text: "Reveal the result."
""",
                encoding="utf-8",
            )
            script = load_script(narration, cue_map=load_cue_map(deck))
        cue = script.steps[0]
        self.assertEqual((cue.slide, cue.step), (1, 1))
        self.assertEqual((cue.scene, cue.cue), ("demo", "reveal"))

    def test_numeric_and_semantic_targets_must_agree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            deck = folder / "deck.html"
            deck.write_text(
                """<section class="slide" data-scene="demo">
<div class="st" data-st="2" data-cue="reveal">result</div>
</section>
""",
                encoding="utf-8",
            )
            narration = folder / "narration.yaml"
            narration.write_text(
                """steps:
  - slide: 1
    step: 1
    scene: demo
    cue: reveal
    text: "Reveal the result."
""",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_script(narration, cue_map=load_cue_map(deck))


if __name__ == "__main__":
    unittest.main()
