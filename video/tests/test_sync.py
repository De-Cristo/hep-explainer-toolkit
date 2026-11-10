from pathlib import Path

import pytest

from video.mux import DEFAULT_SUBTITLE_BAND, burn_in_filter, durations_match
from video.record import RecorderAbort, capture, record_stills
from video.tts import SPACY_MODEL, SPACY_MODEL_WHEEL


def test_durations_match_within_a_fifth_of_a_second():
    assert durations_match(10.0, 10.1, 10.05)
    assert durations_match(10.0, 10.0, 10.2)
    assert not durations_match(10.0, 10.3, 10.0)
    assert not durations_match(10.0, 10.0, 10.21)


def test_burn_in_filter_reserves_a_bottom_band():
    text = burn_in_filter(Path("/tmp/captions.srt"), band=DEFAULT_SUBTITLE_BAND)
    assert "drawbox=x=0:y=ih-180" in text
    assert "MarginV=60" in text
    assert "Alignment=2" in text
    with pytest.raises(ValueError):
        burn_in_filter(Path("c.srt"), band=10)


def test_spacy_model_pin_is_the_3_8_wheel():
    assert SPACY_MODEL == "en_core_web_sm"
    assert "en_core_web_sm-3.8.0" in SPACY_MODEL_WHEEL


def test_record_video_abort_falls_back_to_stills(monkeypatch, tmp_path):
    def boom(*_args, **_kwargs):
        raise RecorderAbort("browser disconnected")

    def stills(*_args, **_kwargs):
        stills.called = True

    stills.called = False
    monkeypatch.setattr("video.record.record_video", boom)
    monkeypatch.setattr("video.record.record_stills", stills)
    result = capture(Path("deck.html"), [], [], tmp_path, mode="auto")
    assert result == {"mode": "stills"}
    assert stills.called


def test_record_stills_drops_frames_from_previous_invocation(monkeypatch, tmp_path):
    stale = tmp_path / "frame.png"
    stale.write_bytes(b"x" * 9001)

    monkeypatch.setattr("video.record._require_playwright", lambda: None)

    def fake_run(plan, timeout):
        assert timeout > 0
        assert not stale.exists()
        stale.write_bytes(b"fresh")
        class Done:
            stdout = ""
        return Done()

    monkeypatch.setattr("video.record._run_node", fake_run)
    record_stills(Path("deck.html"), [(1, 0, stale)], [1.0], tmp_path)
    assert stale.read_bytes() == b"fresh"

def test_forced_video_mode_does_not_hide_an_abort(monkeypatch, tmp_path):
    def boom(*_args, **_kwargs):
        raise RecorderAbort("timed out")

    monkeypatch.setattr("video.record.record_video", boom)
    with pytest.raises(SystemExit, match="timed out"):
        capture(Path("deck.html"), [], [], tmp_path, mode="video")
