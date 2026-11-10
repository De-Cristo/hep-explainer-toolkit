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

from checks.claims import ClaimRegistryError, registry_dependencies
from checks.diagrams import SceneError, load_diagram, resolve_drawing
from checks.documents import document_from_lines
from checks.finaltext import FinalTextError, assert_captions, seal_render_job
from checks.renderjob import RenderInput, make_render_job
from checks.storyboard import (
    StoryboardError,
    check_storyboard,
    format_report as format_storyboard_report,
    narration_segments,
)
from checks.yamlsubset import YamlError, load as load_yaml
from diagrams.render import render_drawing_figure, render_equation, render_figure
from diagrams.states import DiagramStateError, cue_drawing
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
    """Render a checked scene file; segmented narration drives semantic cues."""
    apply_thread_limit(threads)
    scene = Path(scene)
    out = Path(out)
    document = load_yaml(scene.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not document.get("scenes"):
        raise SystemExit(f"{scene} needs a scenes list")

    scene_segments = [
        (item, narration_segments(item))
        for item in document["scenes"]
    ]
    narration_texts = [
        segment.text
        for _item, segments_for_scene in scene_segments
        for segment in segments_for_scene
    ]
    job = make_render_job(
        scene.parent,
        _render_inputs(scene, document),
        trace_documents=[
            document_from_lines(scene.resolve(), "narration", narration_texts)
        ],
        scene_paths=[scene],
    )
    try:
        seal = seal_render_job(job)
        if document.get("brief"):
            storyboard = check_storyboard(scene)
            if not storyboard.ok:
                raise FinalTextError(
                    "storyboard failed on the explicit render job:\n"
                    + format_storyboard_report(storyboard)
                )
        seal.assert_unchanged()
        assert_captions(scene, narration_texts, seal)
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

    captions: list[tuple[float, float, str]] = []
    rendered_segments: list[Path] = []
    cursor = 0.0
    steps = []
    total = len(narration_texts)
    counter = 0
    for item, segments_for_scene in scene_segments:
        scene_id = str(item["id"])
        for segment_index, narration_segment in enumerate(segments_for_scene, 1):
            counter += 1
            cue_id = narration_segment.cue
            suffix = cue_id or f"segment-{segment_index:02d}"
            stem = work_dir / f"{scene_id}-{suffix}"
            picture = _picture_for_segment(scene, item, cue_id, stem.with_name(stem.name + "-picture"))
            wav = stem.with_suffix(".wav")
            spoken = apply_lexicon(narration_segment.text, rules)
            cue_note = f" cue {cue_id}" if cue_id else ""
            print(f"tts {counter}/{total} {scene_id}{cue_note}")
            synthesize(spoken, wav)
            audio = duration_of(wav)
            frames = hold_frames(audio, 0.0, FPS)
            duration = frames / FPS
            movie = stem.with_suffix(".mp4")
            print(
                f"  audio {audio:.2f}s  picture hold {duration:.2f}s  "
                f"({picture.name})"
            )
            fit_segment(
                picture,
                wav,
                movie,
                duration=duration,
                fps=FPS,
                threads=threads,
            )
            rendered_segments.append(movie)
            captions.append((cursor, cursor + duration, narration_segment.text))
            steps.append({
                "id": scene_id,
                "cue": cue_id,
                "text": narration_segment.text,
                "audio_seconds": audio,
                "picture_seconds": duration,
                "picture": str(picture),
            })
            cursor += duration

    silent = work_dir / "picture.mp4"
    if len(rendered_segments) == 1:
        silent = rendered_segments[0]
    else:
        concat_segments(rendered_segments, silent, threads=threads)
    srt = out.with_suffix(".srt")
    try:
        seal.assert_unchanged()
        assert_captions(scene, [text for _start, _end, text in captions], seal)
    except FinalTextError as exc:
        raise SystemExit(str(exc)) from exc
    write_srt(srt, captions)
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
    out.with_suffix(".timings.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {out}  video {video_s:.2f}s audio {audio_s:.2f}s")
    return summary


def _render_inputs(scene: Path, document: dict) -> list[RenderInput]:
    """Declare every file the scene renderer or its scientific checks read."""
    inputs = [RenderInput(scene.resolve(), "scene")]
    brief_raw = document.get("brief")
    if brief_raw:
        inputs.append(
            RenderInput((scene.parent / str(brief_raw)).resolve(), "brief")
        )
    registry_raw = document.get("claim_registry")
    if registry_raw:
        registry_path = (scene.parent / str(registry_raw)).resolve()
        for dependency in registry_dependencies(registry_path):
            inputs.append(RenderInput(dependency, "evidence"))
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


def _picture_for_segment(
    scene_path: Path,
    item: dict,
    cue_id: str | None,
    dest_stem: Path,
) -> Path:
    """Render the visual state named by a narration cue when available."""
    visual = item["visual"]
    if cue_id and visual.get("diagram") and visual.get("cues"):
        cue = next(
            (
                raw for raw in visual["cues"]
                if isinstance(raw, dict) and str(raw.get("id") or "") == cue_id
            ),
            None,
        )
        if cue is None:
            raise SystemExit(f"{item['id']}: no visual cue {cue_id!r}")
        diagram = scene_path.parent / str(visual["diagram"])
        drawing = resolve_drawing(load_diagram(diagram))
        selected = cue_drawing(drawing, cue.get("show_lines"))
        png = dest_stem.with_suffix(".png")
        render_drawing_figure(selected, png, None)
        return png
    return _picture(scene_path, item, dest_stem)


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
    except (ClaimRegistryError, DiagramStateError, SceneError, StoryboardError, YamlError, SystemExit) as exc:
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
