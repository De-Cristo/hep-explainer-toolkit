"""Language runs before the other checks, and only on the rendered bytes."""

from __future__ import annotations

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
