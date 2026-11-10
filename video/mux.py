"""Assemble per-step PNGs and WAVs into an H.264 + AAC MP4, with mov_text captions."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _ffmpeg() -> str:
    binary = shutil.which("ffmpeg")
    if not binary:
        raise SystemExit("ffmpeg is not on PATH")
    return binary


def _run(args: list[str]) -> None:
    completed = subprocess.run(args, text=True, capture_output=True)
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "")[-4000:]
        raise SystemExit(f"ffmpeg failed ({completed.returncode}):\n{tail}")


def hold_frames(audio_seconds: float, pad_seconds: float, fps: int) -> int:
    """Frames to hold a step: narration plus pad, at least one frame."""
    return max(1, int(round((audio_seconds + pad_seconds) * fps)))


def assemble(
    steps: list[tuple[Path, Path, int]],
    out: Path,
    *,
    fps: int,
    threads: int,
) -> None:
    """``steps`` is (png, wav, frame_count). One filter graph, so the clock is the sum of the holds."""
    if not steps:
        raise ValueError("no steps to assemble")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    args: list[str] = [_ffmpeg(), "-y", "-threads", str(threads)]
    filters: list[str] = []
    for index, (png, wav, frames) in enumerate(steps):
        seconds = frames / fps
        args.extend([
            "-loop", "1",
            "-framerate", str(fps),
            "-t", f"{seconds:.6f}",
            "-i", str(png),
            "-i", str(wav),
        ])
        filters.append(
            f"[{2 * index}:v]fps={fps},format=yuv420p,"
            f"trim=duration={seconds:.6f},setpts=PTS-STARTPTS[v{index}]"
        )
        filters.append(
            f"[{2 * index + 1}:a]aresample=48000,"
            f"apad=whole_dur={seconds:.6f},atrim=0:{seconds:.6f},"
            f"asetpts=PTS-STARTPTS[a{index}]"
        )
    interleaved = "".join(f"[v{i}][a{i}]" for i in range(len(steps)))
    filters.append(f"{interleaved}concat=n={len(steps)}:v=1:a=1[v][a]")
    args.extend([
        "-filter_complex", ";".join(filters),
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "stillimage",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-c:a", "aac",
        "-b:a", "160k",
        "-ac", "1",
        "-threads", str(threads),
        "-movflags", "+faststart",
        str(out),
    ])
    _run(args)


def _subtitle_filter_path(srt: Path) -> str:
    # The subtitles filter splits on ':'. Escape the few characters ffmpeg treats specially.
    escaped = str(srt).replace("\\", "\\\\").replace(":", "\\:").replace("'", r"\'")
    style = (
        "FontName=DejaVu Sans,FontSize=22,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,MarginV=48"
    )
    return f"subtitles=filename='{escaped}':charenc=UTF-8:force_style='{style}'"


def add_subtitles(
    video: Path,
    srt: Path,
    out: Path,
    *,
    burn_in: bool,
    threads: int,
) -> None:
    """Embed ``srt`` as a mov_text track. With burn_in, also draw it on the picture."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    picture = video
    if burn_in:
        burned = out.with_suffix(".burned.mp4")
        _run([
            _ffmpeg(), "-y",
            "-i", str(video),
            "-vf", _subtitle_filter_path(srt),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-threads", str(threads),
            "-movflags", "+faststart",
            str(burned),
        ])
        picture = burned
    _run([
        _ffmpeg(), "-y",
        "-i", str(picture),
        "-i", str(srt),
        "-map", "0:v",
        "-map", "0:a",
        "-map", "1:0",
        "-c:v", "copy",
        "-c:a", "copy",
        "-c:s", "mov_text",
        "-metadata:s:s:0", "language=eng",
        "-disposition:s:0", "default",
        "-movflags", "+faststart",
        str(out),
    ])
    if burn_in and picture != out and picture.exists():
        picture.unlink()


def probe(path: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise SystemExit("ffprobe is not on PATH")
    completed = subprocess.run(
        [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration:stream=index,codec_type,codec_name,codec_tag_string",
            "-of", "json",
            str(path),
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    import json
    return json.loads(completed.stdout)
