"""Banned phrasing and word caps from the hep-skills language rules."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from checks.language import ok, scan

ROOT = Path(__file__).resolve().parents[2]


def _write(folder: Path, name: str, text: str) -> Path:
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


class LanguageLintTest(unittest.TestCase):
    def test_banned_phrase_in_narration_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _write(
                folder,
                "narration.txt",
                "We delve into the result. Configure the board prior to the run.\n",
            )
            hits = scan(folder)
        rules = {hit.rule_id for hit in hits if hit.severity == "fail"}
        self.assertIn("delve", rules)
        self.assertIn("prior_to", rules)
        self.assertFalse(ok(hits, strict=False))

    def test_long_bullet_fails_and_a_short_one_does_not(self) -> None:
        words = " ".join(f"w{i}" for i in range(21))
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _write(folder, "talk.html", f"<ul><li>{words}</li><li>Lock the clock.</li></ul>\n")
            hits = scan(folder)
        bullets = [hit for hit in hits if hit.rule_id == "bullet_words"]
        self.assertEqual(len(bullets), 1)
        self.assertIn("21 words", bullets[0].detail)

    def test_long_narration_sentence_warns_until_strict(self) -> None:
        sentence = " ".join(["word"] * 31) + "."
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _write(folder, "narration.txt", sentence + "\n")
            hits = scan(folder)
        self.assertTrue(any(hit.rule_id == "narration_words" and hit.severity == "warn" for hit in hits))
        self.assertTrue(ok(hits, strict=False))
        self.assertFalse(ok(hits, strict=True))

    def test_clean_text_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _write(
                folder,
                "narration.txt",
                "The fit extracts a mass near 125 GeV. Use the clock before readout.\n",
            )
            _write(folder, "talk.html", "<ul><li>Lock the clock before readout.</li></ul>\n")
            hits = scan(folder)
        self.assertEqual(hits, [])
        self.assertTrue(ok(hits, strict=True))

    def test_cli_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _write(folder, "narration.txt", "This paragraph will utilize a banned verb.\n")
            completed = subprocess.run(
                [sys.executable, "-m", "checks.language", "scan", str(folder)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("utilize", completed.stdout)


if __name__ == "__main__":
    unittest.main()
