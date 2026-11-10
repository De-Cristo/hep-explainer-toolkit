"""Deck folder + narration file -> MP4."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from video.deck import load_deck, resolve_deck_inputs, walk_states
from video.lexicon import apply_lexicon, load_lexicon
from video.mux import add_subtitles, assemble, hold_frames, probe
from video.narration import Script, check_against_deck, load_script
from video.record import record_frames
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
    pad: float | None = None,
    voice: str | None = None,
    speed: float | None = None,
    precision: str = "int8",
    model: Path | None = None,
    voices: Path | None = None,
    work_dir: Path | None = None,
    check_only: bool = False,
    synthesize=None,
) -> dict:
    """Run the pipeline. ``synthesize(spoken, wav_path) -> None`` overrides Kokoro (tests)."""
    apply_thread_limit(threads)
    html_path, narration_path = resolve_deck_inputs(Path(deck), Path(narration) if narration else None)
    script: Script = load_script(narration_path)
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
        from video.tts import KokoroSpeaker, ensure_weights, wav_duration

        model_path, voices_path = ensure_weights(precision, model, voices)
        speaker = KokoroSpeaker(
            model_path, voices_path, threads, script.lang, script.speed, script.voice,
        )

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
        phonemes = speaker.phonemes(say) if speaker is not None else ""
        timed.append(TimedStep(
            cue.slide, cue.step, cue.text, say, audio_seconds, frames, start, end, phonemes,
        ))
        shots.append((cue.slide, cue.step, png))
        assembly.append((png, wav, frames))
        print(f"  audio {audio_seconds:.2f}s  hold {frames / FPS:.2f}s")

    print("recording deck")
    record_frames(html_path, shots)

    silent_subs = work_dir / "picture.mp4"
    print("muxing picture and audio")
    assemble(assembly, silent_subs, fps=FPS, threads=threads)

    srt_path = out.with_suffix(".srt")
    write_srt(srt_path, [(step.start, step.end, step.text) for step in timed])
    print("muxing subtitles")
    add_subtitles(silent_subs, srt_path, out, burn_in=burn_in, threads=threads)

    info = probe(out)
    duration = float(info["format"]["duration"])
    report = {
        "output": str(out),
        "srt": str(srt_path),
        "title": script.title,
        "voice": script.voice,
        "precision": precision if speaker is not None else "synthetic",
        "threads": threads,
        "fps": FPS,
        "pad_seconds": script.pad_seconds,
        "burn_in": burn_in,
        "duration_seconds": frame_cursor / FPS,
        "probed_duration_seconds": duration,
        "steps": [asdict(step) for step in timed],
    }
    timings = out.with_suffix(".timings.json")
    timings.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    print(f"duration {duration:.2f}s (timeline {frame_cursor / FPS:.2f}s)")
    print(f"captions {srt_path}")
    return report
