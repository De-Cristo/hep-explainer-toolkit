"""Synthetic end-to-end scene render: no Kokoro, browser, or network."""

from __future__ import annotations

import binascii
import shutil
import struct
import tempfile
import unittest
import wave
import zlib
from pathlib import Path

from video.explain import render_explanation
from video.mux import probe


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)
    )


def _solid_png(path: Path, width: int = 32, height: int = 18) -> None:
    row = bytes([245, 245, 245]) * width
    raw = b"".join(b"\x00" + row for _ in range(height))
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )
    path.write_bytes(payload)


def _silence(_text: str, dest: Path, seconds: float = 0.4) -> None:
    rate = 24000
    frames = int(rate * seconds)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * frames)


class SceneRenderIntegrationTest(unittest.TestCase):
    def test_synthetic_scene_writes_video_subtitles_and_seal(self) -> None:
        self.assertIsNotNone(shutil.which("ffmpeg"), "CI image needs ffmpeg")
        self.assertIsNotNone(shutil.which("ffprobe"), "CI image needs ffprobe")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "image.png"
            _solid_png(image)
            (root / "sources.yaml").write_text(
                """files:
  - path: image.png
    source:
      type: arxiv
      arxiv: "1808.08242"
""",
                encoding="utf-8",
            )
            (root / "excerpt.yaml").write_text(
                """arxiv: "1808.08242"
locator: "Abstract sentence 2 (production)"
quote: "The main contribution to this result is from processes in which Higgs bosons are produced in association with a W or Z boson (VH)."
""",
                encoding="utf-8",
            )
            scene = root / "scene.yaml"
            scene.write_text(
                """title: "Synthetic integration"
scenes:
  - id: intro
    narration: "The main contribution comes from Higgs bosons produced with a W or Z boson."
    visual:
      kind: figure
      file: image.png
    claims:
      - id: words
        kind: claim
        text: "The main contribution comes from Higgs bosons produced with a W or Z boson."
        citation:
          arxiv: "1808.08242"
          locator: "Abstract sentence 2 (production)"
        excerpt: excerpt.yaml
""",
                encoding="utf-8",
            )
            out = root / "out.mp4"
            report = render_explanation(
                scene,
                out,
                threads=1,
                synthesize=_silence,
            )

            self.assertTrue(out.is_file())
            self.assertTrue((root / "out.srt").is_file())
            self.assertEqual(len(report["scenes"]), 1)
            self.assertIsNone(report["scenes"][0]["cue"])
            self.assertIn(str((root / "sources.yaml").resolve()), report["final_text_sha256"])
            info = probe(out)
            codecs = {stream["codec_name"] for stream in info["streams"]}
            self.assertIn("h264", codecs)
            self.assertIn("aac", codecs)
            self.assertIn("mov_text", codecs)


if __name__ == "__main__":
    unittest.main()
