from __future__ import annotations

import unittest

from checks.doctor import evaluate


class DoctorTest(unittest.TestCase):
    def test_capabilities_are_independent(self) -> None:
        probes = {
            "python": True,
            "pdflatex": True,
            "pdftocairo": True,
            "node": True,
            "ffmpeg": True,
            "ffprobe": True,
            "playwright": False,
            "pyyaml": True,
            "soundfile": True,
            "kokoro": False,
            "espeak-ng": False,
            "manim": False,
            "latex": False,
            "dvisvgm": False,
        }
        report = evaluate(probes)
        self.assertTrue(report["checks"]["ready"])
        self.assertTrue(report["diagrams"]["ready"])
        self.assertFalse(report["slide-video"]["ready"])
        self.assertTrue(report["theory-video"]["ready"])
        self.assertFalse(report["narrated-theory-video"]["ready"])
        self.assertFalse(report["manim"]["ready"])

    def test_missing_ffmpeg_blocks_media_not_checks(self) -> None:
        probes = {name: True for name in {
            "python", "pdflatex", "pdftocairo", "node", "ffmpeg", "ffprobe",
            "playwright", "pyyaml", "soundfile", "kokoro", "espeak-ng",
            "manim", "latex", "dvisvgm",
        }}
        probes["ffmpeg"] = False
        report = evaluate(probes)
        self.assertTrue(report["checks"]["ready"])
        self.assertTrue(report["diagrams"]["ready"])
        self.assertFalse(report["slide-video"]["ready"])
        self.assertFalse(report["theory-video"]["ready"])
        self.assertFalse(report["manim"]["ready"])


if __name__ == "__main__":
    unittest.main()
