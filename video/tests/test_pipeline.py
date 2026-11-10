"""Recorder + ffmpeg, with a stand-in for Kokoro so the clock is exact."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import pytest

from video.mux import add_subtitles, assert_av_sync, probe
from video.pipeline import render

TOY = Path(__file__).resolve().parents[1] / "examples" / "toy-peak"
AUDIO_SECONDS = 0.8
PAD = 0.2


def _tone(path: Path, seconds: float, rate: int = 24000) -> None:
    frames = int(seconds * rate)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        samples = bytearray()
        for i in range(frames):
            value = int(8000 * math.sin(2 * math.pi * 440 * i / rate))
            samples += struct.pack("<h", value)
        handle.writeframes(samples)


def _synthesize(text: str, dest: Path) -> None:
    assert text
    _tone(dest, AUDIO_SECONDS)


def _subtitle_count(path: Path) -> int:
    import subprocess
    text = subprocess.check_output(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:s:0", "-f", "srt", "-"],
        text=True,
    )
    return text.count("-->")


def _luma(video: Path, y: int) -> int:
    import subprocess
    data = subprocess.check_output([
        "ffmpeg", "-v", "error", "-ss", "0.2", "-i", str(video),
        "-frames:v", "1",
        # yuv420 rejects a 1px crop (the height rounds to 0). A 2px strip is enough.
        "-vf", f"format=rgb24,crop=8:2:0:{y},scale=1:1,format=gray",
        "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
    ])
    return data[0]


def test_pipeline_duration_and_subtitle_track(tmp_path):
    out = tmp_path / "toy.mp4"
    report = render(
        TOY,
        out=out,
        threads=2,
        pad=PAD,
        work_dir=tmp_path / "work",
        synthesize=_synthesize,
        capture_mode="auto",
    )
    assert out.is_file()
    assert Path(report["srt"]).is_file()
    expected = report["duration_seconds"]
    # 6 steps * (0.8 + 0.2) = 6.0s, on a 30 fps grid.
    assert expected == pytest.approx(6.0, abs=1e-6)
    video_s, audio_s = assert_av_sync(out, expected)
    assert video_s == pytest.approx(expected, abs=0.2)
    assert audio_s == pytest.approx(expected, abs=0.2)
    assert report["capture"] in {"video", "stills"}
    info = probe(out)
    codecs = [stream["codec_name"] for stream in info["streams"]]
    assert "h264" in codecs
    assert "aac" in codecs
    assert "mov_text" in codecs
    assert _subtitle_count(out) == 6
    # Soft captions do not paint a band over the slide.
    assert _luma(out, 1000) > 160

    burned = tmp_path / "toy-burned.mp4"
    add_subtitles(out, Path(report["srt"]), burned, burn_in=True, threads=2, subtitle_band=180)
    assert_av_sync(burned, expected)
    # The burn-in band is the bottom 180px, so y=1000 is inside it and darker
    # than the slide body. Axis labels sit above that strip.
    assert _luma(burned, 1000) < 80
    assert _luma(burned, 400) > 160

    jargon = next(step for step in report["steps"] if step["slide"] == 3 and step["step"] == 1)
    assert "inverse femtobarns" in jargon["spoken"]
    assert "J/psi" in jargon["text"]
