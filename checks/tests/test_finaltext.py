"""Language runs before the other checks, and only on the rendered bytes."""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from checks.finaltext import FinalTextError, Seal, assert_captions, run_ordered_checks, seal_for_render

TOY = Path(__file__).resolve().parents[2] / "video" / "examples" / "toy-peak"


def _quiet(**_kwargs):
    return []


class OrderTest(unittest.TestCase):
    def test_language_failure_does_not_run_later_checks(self) -> None:
        calls: list[str] = []

        def language(_paths):
            calls.append("language")
            return ["narration.txt:1 delve delve"]

        def later(name):
            def run(_root, _paths):
                calls.append(name)
                return []
            return run

        with self.assertRaises(FinalTextError) as caught:
            run_ordered_checks(
                TOY,
                [TOY / "narration.yaml"],
                runners={
                    "language": language,
                    "provenance": later("provenance"),
                    "traceability": later("traceability"),
                    "diagrams": later("diagrams"),
                },
            )
        self.assertEqual(calls, ["language"])
        self.assertIn("later checks were not run", str(caught.exception))

    def test_changed_file_is_not_what_gets_rendered(self) -> None:
        narration = TOY / "narration.yaml"
        seal = Seal({str(narration.resolve()): "0" * 64})
        with self.assertRaises(FinalTextError) as caught:
            seal.assert_unchanged()
        self.assertIn("changed after the checks", str(caught.exception))

    def test_caption_must_be_in_the_sealed_narration(self) -> None:
        narration = TOY / "narration.yaml"
        seal = seal_for_render(TOY / "deck.html", narration)
        assert_captions(narration, ["This toy talk is simulated. It is not a CMS result."], seal)
        with self.assertRaises(FinalTextError):
            assert_captions(narration, ["This sentence was the pre-rewrite draft."], seal)

    def test_external_narration_is_traced_as_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as deck_tmp, tempfile.TemporaryDirectory() as narration_tmp:
            deck = Path(deck_tmp)
            slide = deck / "deck.html"
            slide.write_text("<div class=\"slide\">Public toy deck.</div>\n", encoding="utf-8")
            (deck / "sources.yaml").write_text(
                textwrap.dedent(
                    """
                    files:
                      - path: deck.html
                        source:
                          type: arxiv
                          arxiv: "1808.08242"
                    sources:
                      - id: known_mass
                        value: 125
                        unit: GeV
                        source:
                          type: paper
                          arxiv: "1808.08242"
                    """
                ),
                encoding="utf-8",
            )
            narration = Path(narration_tmp) / "narration.yaml"
            narration.write_text(
                "steps:\n"
                "  - slide: 1\n"
                "    step: 0\n"
                "    text: The planted value is 987654 GeV.\n",
                encoding="utf-8",
            )
            with self.assertRaises(FinalTextError) as caught:
                seal_for_render(slide, narration)
        self.assertIn("987654", str(caught.exception))

    def test_custom_named_scene_is_not_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            scene = folder / "custom-scene.yaml"
            scene.write_text(
                textwrap.dedent(
                    """
                    title: custom
                    scenes:
                      - id: bad
                        narration: "A planted unsupported statement."
                        visual:
                          kind: slide
                        claims:
                          - id: words
                            kind: claim
                            text: "A planted unsupported statement."
                    """
                ),
                encoding="utf-8",
            )
            with self.assertRaises(FinalTextError) as caught:
                run_ordered_checks(folder, [scene])
        self.assertIn("diagrams failed", str(caught.exception))
    def test_toy_deck_seals_the_files_that_render(self) -> None:
        narration = (TOY / "narration.yaml").resolve()
        slide = (TOY / "deck.html").resolve()
        original = narration.read_bytes()
        seal = seal_for_render(slide, narration)
        self.assertEqual(set(seal.hashes), {str(slide), str(narration)})
        seal.assert_unchanged()
        narration.write_bytes(original + b"\n")
        try:
            with self.assertRaises(FinalTextError):
                seal.assert_unchanged()
        finally:
            narration.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
