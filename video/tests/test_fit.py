"""A short clip is held out to the narration, which is the 20 s / 44 s bug."""

from __future__ import annotations

import math
import shutil
import struct
import wave
from pathlib import Path

import pytest

from video.mux import assert_av_sync, fit_segment, probe

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


def _tone(path: Path, seconds: float, rate: int = 8000) -> None:
    frames = int(seconds * rate)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        samples = bytearray()
        for i in range(frames):
            value = int(4000 * math.sin(2 * math.pi * 440 * i / rate))
            samples += struct.pack("<h", value)
        handle.writeframes(samples)


def _clip(path: Path, seconds: float) -> None:
    import subprocess
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=black:s=320x180:d={seconds}",
            "-r", "10", "-pix_fmt", "yuv420p",
            str(path),
        ],
        check=True, capture_output=True,
    )


def test_short_clip_is_held_to_the_narration(tmp_path: Path) -> None:
    clip = tmp_path / "draw.mp4"
    wav = tmp_path / "narration.wav"
    out = tmp_path / "segment.mp4"
    _clip(clip, 0.4)
    _tone(wav, 1.2)
    fit_segment(clip, wav, out, duration=1.2, fps=10, threads=1, width=320, height=180)
    video_s, audio_s = assert_av_sync(out, 1.2, tolerance=0.2)
    assert video_s == pytest.approx(1.2, abs=0.2)
    assert audio_s == pytest.approx(1.2, abs=0.2)
    info = probe(out)
    kinds = {stream["codec_type"] for stream in info["streams"]}
    assert {"video", "audio"} <= kinds


def test_still_image_lasts_as_long_as_the_narration(tmp_path: Path) -> None:
    import subprocess
    png = tmp_path / "slide.png"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=white:s=320x180", "-frames:v", "1", str(png)],
        check=True, capture_output=True,
    )
    wav = tmp_path / "narration.wav"
    out = tmp_path / "segment.mp4"
    _tone(wav, 0.8)
    fit_segment(png, wav, out, duration=0.8, fps=10, threads=1, width=320, height=180)
    assert_av_sync(out, 0.8, tolerance=0.2)
