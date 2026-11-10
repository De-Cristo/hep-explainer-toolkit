"""Scene file to a narrated MP4.

Extends the deck assembler: each scene is a still (diagram, equation slide,
figure, or plot) or a Manim clip, held or padded so the picture lasts as
long as that scene's Kokoro narration. Subtitles are the scene text on that
same clock.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from checks.diagrams import SceneError
from checks.documents import document_from_lines
from checks.finaltext import FinalTextError, assert_captions, seal_render_job
from checks.renderjob import RenderInput, make_render_job
from checks.yamlsubset import YamlError, load as load_yaml
from diagrams.render import render_equation, render_figure
from video.lexicon import apply_lexicon, load_lexicon
from video.mux import (
    add_subtitles,
    assert_av_sync,
    concat_segments,
    fit_segment,
    hold_frames,
)
from video.srt import write_srt
from video.threads import apply_thread_limit

FPS = 30


def render_explanation(
    scene: Path,
    out: Path,
    *,
    threads: int = 4,
    voice: str = "af_heart",
    work_dir: Path | None = None,
    synthesize=None,
) -> dict:
    """Render ``scene`` to ``out``. ``synthesize(text, wav)`` replaces Kokoro in tests.

    Language runs first. Provenance, number trace, and the diagram check then
    read this scene file. Rendering uses that text and stops if its hash changed.
    """
    apply_thread_limit(threads)
    scene = Path(scene)
    out = Path(out)
    document = load_yaml(scene.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not document.get("scenes"):
        raise SystemExit(f"{scene} needs a scenes list")
    narrations = [
        " ".join(str(item.get("narration") or "").split())
        for item in document["scenes"]
    ]
    job = make_render_job(
        scene.parent,
        _render_inputs(scene, document),
        trace_documents=[
            document_from_lines(scene.resolve(), "narration", narrations)
        ],
        scene_paths=[scene],
    )
    try:
        seal = seal_render_job(job)
        assert_captions(scene, narrations, seal)
    except FinalTextError as exc:
        raise SystemExit(str(exc)) from exc

    if work_dir is None:
        work_dir = out.parent / f"{out.stem}-work"
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    rules = load_lexicon(None)
    speaker = None
    if synthesize is None:
        from video.tts import KokoroSpeaker, wav_duration

        speaker = KokoroSpeaker(threads, "en-us", 1.0, voice)

        def synthesize(text: str, dest: Path, _speaker=speaker) -> None:
            _speaker.write(text, dest)

        duration_of = wav_duration
    else:
        from video.tts import wav_duration
        duration_of = wav_duration

    cues: list[tuple[float, float, str]] = []
    segments: list[Path] = []
    cursor = 0.0
    steps = []
    for index, item in enumerate(document["scenes"]):
        scene_id = str(item["id"])
        narration = " ".join(str(item.get("narration") or "").split())
        if not narration:
            raise SystemExit(f"{scene_id} has no narration")
        picture = _picture(scene, item, work_dir / f"{scene_id}-picture")
        wav = work_dir / f"{scene_id}.wav"
        spoken = apply_lexicon(narration, rules)
        print(f"tts {index + 1}/{len(document['scenes'])} {scene_id}")
        synthesize(spoken, wav)
        audio = duration_of(wav)
        frames = hold_frames(audio, 0.0, FPS)
        duration = frames / FPS
        segment = work_dir / f"{scene_id}.mp4"
        print(f"  audio {audio:.2f}s  picture hold {duration:.2f}s  ({picture.name})")
        fit_segment(picture, wav, segment, duration=duration, fps=FPS, threads=threads)
        segments.append(segment)
        cues.append((cursor, cursor + duration, narration))
        steps.append({
            "id": scene_id,
            "audio_seconds": audio,
            "picture_seconds": duration,
            "picture": str(picture),
        })
        cursor += duration

    silent = work_dir / "picture.mp4"
    if len(segments) == 1:
        silent = segments[0]
    else:
        concat_segments(segments, silent, threads=threads)
    srt = out.with_suffix(".srt")
    try:
        seal.assert_unchanged()
        assert_captions(scene, [text for _start, _end, text in cues], seal)
    except FinalTextError as exc:
        raise SystemExit(str(exc)) from exc
    write_srt(srt, cues)
    out.parent.mkdir(parents=True, exist_ok=True)
    add_subtitles(silent, srt, out, burn_in=False, threads=threads)
    video_s, audio_s = assert_av_sync(out, cursor)
    summary = {
        "output": str(out),
        "srt": str(srt),
        "duration_seconds": cursor,
        "video_seconds": video_s,
        "audio_seconds": audio_s,
        "scenes": steps,
        "final_text_sha256": seal.hashes,
    }
    out.with_suffix(".timings.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"wrote {out}  video {video_s:.2f}s audio {audio_s:.2f}s")
    return summary


def _render_inputs(scene: Path, document: dict) -> list[RenderInput]:
    """Declare every file the scene renderer or its scientific checks read."""
    inputs = [RenderInput(scene.resolve(), "scene")]
    for item in document["scenes"]:
        visual = item.get("visual") or {}
        raw_diagram = visual.get("diagram")
        if raw_diagram:
            inputs.append(
                RenderInput((scene.parent / str(raw_diagram)).resolve(), "diagram")
            )
        raw_file = visual.get("file")
        if raw_file:
            inputs.append(
                RenderInput((scene.parent / str(raw_file)).resolve(), "asset")
            )
        for claim in item.get("claims") or []:
            raw = claim.get("excerpt")
            if raw:
                inputs.append(
                    RenderInput((scene.parent / str(raw)).resolve(), "evidence")
                )
    unique: list[RenderInput] = []
    seen: set[Path] = set()
    for item in inputs:
        path = item.path.resolve()
        if path not in seen:
            seen.add(path)
            unique.append(RenderInput(path, item.role))
    return unique


def _picture(scene_path: Path, item: dict, dest_stem: Path) -> Path:
    visual = item["visual"]
    kind = str(visual.get("kind"))
    motion = str(visual.get("motion") or "still")
    if kind in {"diagram", "manim"} or "diagram" in visual:
        diagram = scene_path.parent / str(visual["diagram"])
        if kind == "manim" or motion == "build":
            from diagrams.render import render_animation
            movie = dest_stem.with_suffix(".mp4")
            render_animation(diagram, movie)
            return movie
        png = dest_stem.with_suffix(".png")
        render_figure(diagram, png, None)
        return png
    if kind == "slide":
        equations = visual.get("equations") or []
        if not equations:
            raise SystemExit(f"{item['id']} slide has no equations")
        tex = r"\\".join(str(entry["tex"]) for entry in equations)
        png = dest_stem.with_suffix(".png")
        render_equation(tex, png)
        return png
    if kind in {"figure", "plot"}:
        raw = visual.get("file")
        if not raw:
            raise SystemExit(f"{item['id']} needs visual.file")
        path = (scene_path.parent / str(raw)).resolve()
        if not path.is_file():
            raise SystemExit(f"missing picture {path}")
        return path
    raise SystemExit(f"unsupported visual {kind}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m video.explain",
        description="Render a theory scene file to a narrated MP4.",
    )
    parser.add_argument("scene", type=Path)
    parser.add_argument("-o", "--out", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--voice", default="af_heart")
    parser.add_argument("--work-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        render_explanation(
            args.scene, args.out,
            threads=args.threads, voice=args.voice, work_dir=args.work_dir,
        )
    except (SceneError, YamlError, SystemExit) as exc:
        if isinstance(exc, SystemExit):
            if isinstance(exc.code, str):
                print(exc.code, file=sys.stderr)
                return 1
            if exc.code not in (0, None):
                return int(exc.code)
            return 0
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
