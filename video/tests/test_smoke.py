"""End-to-end smoke: Kokoro on CPU, then the same mux, on the toy deck.

The first run downloads hexgrad/Kokoro-82M into the Hugging Face cache and
spaCy's en_core_web_sm into the environment if it is not already installed.
Skip with HEP_SKIP_SMOKE=1.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from video.mux import assert_av_sync, probe
from video.pipeline import render

TOY = Path(__file__).resolve().parents[1] / "examples" / "toy-peak"

pytestmark = pytest.mark.smoke


@pytest.mark.skipif(os.environ.get("HEP_SKIP_SMOKE") == "1", reason="HEP_SKIP_SMOKE=1")
def test_kokoro_pipeline_writes_an_mp4_with_captions(tmp_path):
    out = tmp_path / "toy-peak.mp4"
    report = render(
        TOY,
        out=out,
        threads=4,
        work_dir=tmp_path / "work",
        capture_mode="auto",
    )
    assert out.is_file()
    assert out.stat().st_size > 10_000
    info = probe(out)
    codecs = [stream["codec_name"] for stream in info["streams"]]
    assert codecs.count("h264") == 1
    assert "aac" in codecs
    assert "mov_text" in codecs
    video_s, audio_s = assert_av_sync(out, report["duration_seconds"])
    probed = float(info["format"]["duration"])
    assert probed == pytest.approx(video_s, abs=0.05)
    assert abs(video_s - audio_s) <= 0.2
    # Six short sentences plus pad. A silent or runaway file fails this.
    assert 8.0 < probed < 90.0
    assert len(report["steps"]) == 6
    assert all(step["audio_seconds"] > 0.3 for step in report["steps"])
    jargon = report["steps"][-1]
    assert "teraelectronvolts" in jargon["spoken"]
    assert jargon["phonemes"]
    print("SMOKE duration", round(probed, 3))
    for step in report["steps"]:
        print(
            f"  slide {step['slide']} step {step['step']} "
            f"audio {step['audio_seconds']:.2f}s hold {step['end'] - step['start']:.2f}s"
        )
        print(f"    spoken: {step['spoken']}")
        print(f"    phonemes: {step['phonemes']}")
