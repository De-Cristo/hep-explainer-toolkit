"""Deck folder + narration file -> MP4."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from checks.documents import load_document
from checks.finaltext import FinalTextError, assert_captions, seal_render_job
from checks.renderjob import RenderInput, make_render_job
from video.deck import load_deck, resolve_deck_inputs, walk_states
from video.lexicon import apply_lexicon, load_lexicon
from video.mux import (
    DEFAULT_SUBTITLE_BAND,
    SyncError,
    add_subtitles,
    assemble,
    assemble_recording,
    assert_av_sync,
    hold_frames,
)
from video.narration import Script, check_against_deck, load_script, script_document
from video.record import RecorderAbort, capture, record_stills
from video.srt import write_srt
from video.threads import apply_thread_limit

FPS = 30


@dataclass
class TimedStep:
    slide: int
    step: int
    text: str
    spoken: str
    audio_seconds: float
    frames: int
    start: float
    end: float
    phonemes: str = ""


def render(
    deck: Path,
    narration: Path | None = None,
    out: Path | None = None,
    *,
    threads: int = 4,
    burn_in: bool = False,
    subtitle_band: int = DEFAULT_SUBTITLE_BAND,
    pad: float | None = None,
    voice: str | None = None,
    speed: float | None = None,
    capture_mode: str = "auto",
    work_dir: Path | None = None,
    check_only: bool = False,
    synthesize=None,
) -> dict:
    """Run the pipeline. ``synthesize(spoken, wav_path) -> None`` overrides Kokoro (tests).

    The language pass runs first. Provenance, number trace, and the diagram
    check then read those same files. Rendering uses that text, and stops if
    the files no longer match the hash the checks saw.
    """
    apply_thread_limit(threads)
    html_path, narration_path = resolve_deck_inputs(Path(deck), Path(narration) if narration else None)
    script: Script = load_script(narration_path)
    trace_documents = [
        *load_document(html_path, "slide"),
        script_document(script),
    ]
    job = make_render_job(
        html_path.parent,
        [
            RenderInput(html_path, "slide"),
            RenderInput(narration_path, "narration"),
        ],
        trace_documents=trace_documents,
    )
    try:
        seal = seal_render_job(job)
        seal.assert_unchanged()
        assert_captions(narration_path, [cue.text for cue in script.steps], seal)
    except FinalTextError as exc:
        raise SystemExit(str(exc)) from exc
    if voice:
        script = Script(
            script.title, voice, script.lang, script.speed, script.pad_seconds,
            script.lexicon, script.steps, script.path,
        )
    if speed is not None:
        if not 0.5 <= speed <= 2.0:
            raise SystemExit(f"speed {speed} is outside the Kokoro range 0.5..2.0")
        script = Script(
            script.title, script.voice, script.lang, speed, script.pad_seconds,
            script.lexicon, script.steps, script.path,
        )
    if pad is not None:
        if pad < 0:
            raise SystemExit("pad must be >= 0")
        script = Script(
            script.title, script.voice, script.lang, script.speed, pad,
            script.lexicon, script.steps, script.path,
        )

    states = walk_states(load_deck(html_path))
    check_against_deck(script, states)
    rules = load_lexicon(script.lexicon)
    spoken = [apply_lexicon(cue.text, rules) for cue in script.steps]

    print(f"deck: {html_path}")
    print(f"narration: {narration_path}")
    print(f"steps: {len(script.steps)}  voice: {script.voice}  threads: {threads}")
    for cue, say in zip(script.steps, spoken):
        line = f"  slide {cue.slide} step {cue.step}: {say}"
        print(line)

    if check_only:
        return {"steps": [{"slide": c.slide, "step": c.step, "text": c.text, "spoken": s}
                          for c, s in zip(script.steps, spoken)]}

    if out is None:
        out = html_path.parent / "build" / f"{html_path.stem}.mp4"
    out = Path(out)
    if work_dir is None:
        work_dir = out.parent / f"{out.stem}-work"
    work_dir = Path(work_dir)
    frames_dir = work_dir / "frames"
    audio_dir = work_dir / "audio"
    frames_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    speaker = None
    if synthesize is None:
        from video.tts import KokoroSpeaker, wav_duration

        speaker = KokoroSpeaker(threads, script.lang, script.speed, script.voice)

        def synthesize(text: str, dest: Path, _speaker=speaker) -> None:
            _speaker.write(text, dest)

        duration_of = wav_duration
    else:
        from video.tts import wav_duration
        duration_of = wav_duration

    timed: list[TimedStep] = []
    frame_cursor = 0
    shots: list[tuple[int, int, Path]] = []
    assembly: list[tuple[Path, Path, int]] = []
    for index, (cue, say) in enumerate(zip(script.steps, spoken)):
        wav = audio_dir / f"s{cue.slide:02d}-st{cue.step:02d}.wav"
        png = frames_dir / f"s{cue.slide:02d}-st{cue.step:02d}.png"
        print(f"tts {index + 1}/{len(script.steps)} slide {cue.slide} step {cue.step}")
        synthesize(say, wav)
        audio_seconds = duration_of(wav)
        frames = hold_frames(audio_seconds, script.pad_seconds, FPS)
        start = frame_cursor / FPS
        frame_cursor += frames
        end = frame_cursor / FPS
        phonemes = speaker.last_phonemes if speaker is not None else ""
        timed.append(TimedStep(
            cue.slide, cue.step, cue.text, say, audio_seconds, frames, start, end, phonemes,
        ))
        shots.append((cue.slide, cue.step, png))
        assembly.append((png, wav, frames))
        print(f"  audio {audio_seconds:.2f}s  hold {frames / FPS:.2f}s")

    holds = [step.end - step.start for step in timed]
    timeline = frame_cursor / FPS
    silent_subs = work_dir / "picture.mp4"
    pictures = _capture_synced(
        html_path, shots, holds, assembly, work_dir, silent_subs,
        capture_mode=capture_mode, threads=threads, timeline=timeline,
    )

    srt_path = out.with_suffix(".srt")
    caption_text = [step.text for step in timed]
    try:
        seal.assert_unchanged()
        assert_captions(narration_path, caption_text, seal)
    except FinalTextError as exc:
        raise SystemExit(str(exc)) from exc
    write_srt(srt_path, [(step.start, step.end, step.text) for step in timed])
    print("muxing subtitles" + (" (bottom band burn-in)" if burn_in else " (mov_text only)"))
    add_subtitles(
        silent_subs, srt_path, out,
        burn_in=burn_in, threads=threads, subtitle_band=subtitle_band,
    )
    video_s, audio_s = assert_av_sync(out, timeline)
    report = {
        "output": str(out),
        "srt": str(srt_path),
        "title": script.title,
        "voice": script.voice,
        "engine": "kokoro" if speaker is not None else "synthetic",
        "threads": threads,
        "fps": FPS,
        "pad_seconds": script.pad_seconds,
        "burn_in": burn_in,
        "subtitle_band": subtitle_band if burn_in else 0,
        "capture": pictures,
        "duration_seconds": timeline,
        "video_seconds": video_s,
        "audio_seconds": audio_s,
        "probed_duration_seconds": video_s,
        "steps": [asdict(step) for step in timed],
        "final_text_sha256": seal.hashes,
    }
    timings = out.with_suffix(".timings.json")
    timings.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    print(
        f"duration video {video_s:.2f}s audio {audio_s:.2f}s "
        f"timeline {timeline:.2f}s ({pictures})"
    )
    print(f"captions {srt_path}")
    return report


def _capture_synced(
    html_path: Path,
    shots: list[tuple[int, int, Path]],
    holds: list[float],
    assembly: list[tuple[Path, Path, int]],
    work_dir: Path,
    silent_subs: Path,
    *,
    capture_mode: str,
    threads: int,
    timeline: float,
) -> str:
    """Record, then rebuild from stills if the moving picture drifts from the audio."""
    pictures = capture(html_path, shots, holds, work_dir, mode=capture_mode)
    if pictures["mode"] == "video":
        try:
            print("muxing recordVideo against measured audio")
            assemble_recording(
                pictures["webm"], pictures["lead"], assembly, silent_subs,
                fps=FPS, threads=threads,
            )
            return "video"
        except (SyncError, RecorderAbort, SystemExit) as exc:
            if capture_mode == "video":
                raise SystemExit(str(exc)) from exc
            print(f"recordVideo drifted from the audio ({exc}); rebuilding from screenshots")
    if pictures["mode"] != "stills":
        record_stills(html_path, shots, holds, work_dir)
    print("muxing screenshots held for each measured audio duration")
    assemble(assembly, silent_subs, fps=FPS, threads=threads)
    try:
        assert_av_sync(silent_subs, timeline)
    except SyncError as exc:
        raise SystemExit(str(exc)) from exc
    return "stills"
