"""Assemble picture and audio into an H.264 + AAC MP4, with mov_text captions.

The soft ``mov_text`` track is the default. Burn-in is optional and draws the
cues inside a bottom band so they do not sit on plot axis labels.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

# Video, audio, and the timeline built from measured step durations must agree.
SYNC_TOLERANCE_S = 0.2
# Bottom strip reserved for burned-in captions on a 1920×1080 frame.
DEFAULT_SUBTITLE_BAND = 180


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


def durations_match(
    video_s: float,
    audio_s: float,
    timeline_s: float,
    tolerance: float = SYNC_TOLERANCE_S,
) -> bool:
    """True when picture, sound, and the sum of measured holds agree."""
    return (
        abs(video_s - audio_s) <= tolerance
        and abs(video_s - timeline_s) <= tolerance
        and abs(audio_s - timeline_s) <= tolerance
    )


class SyncError(RuntimeError):
    """The finished file's picture and sound are more than ~0.2s apart."""


def stream_clock(info: dict) -> tuple[float, float]:
    video = audio = None
    for stream in info.get("streams", []):
        raw = stream.get("duration")
        if raw in (None, "N/A", ""):
            continue
        if stream.get("codec_type") == "video" and video is None:
            video = float(raw)
        elif stream.get("codec_type") == "audio" and audio is None:
            audio = float(raw)
    container = float(info["format"]["duration"])
    return video if video is not None else container, audio if audio is not None else container


def assert_av_sync(path: Path, timeline_s: float, tolerance: float = SYNC_TOLERANCE_S) -> tuple[float, float]:
    """Fail if video, audio, and the measured timeline differ by more than ``tolerance``."""
    video_s, audio_s = stream_clock(probe(path))
    if not durations_match(video_s, audio_s, timeline_s, tolerance):
        raise SyncError(
            f"audio and video drifted apart in {path}: "
            f"video {video_s:.3f}s, audio {audio_s:.3f}s, timeline {timeline_s:.3f}s "
            f"(limit {tolerance:.1f}s)"
        )
    return video_s, audio_s


def _escape_filter_path(path: Path) -> str:
    # The subtitles filter splits on ':'. Escape the few characters ffmpeg treats specially.
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", r"\'")


def burn_in_filter(srt: Path, band: int = DEFAULT_SUBTITLE_BAND) -> str:
    """Draw cues inside a bottom band, above where axis labels usually sit.

    ``band`` is the height of that strip in pixels on a 1080-tall frame.
    Alignment 2 plus MarginV keeps the glyphs inside the strip rather than
    on the plot.
    """
    if band < 64:
        raise ValueError(f"subtitle band must be at least 64px, got {band}")
    margin_v = max(40, band // 3)
    style = (
        "FontName=DejaVu Sans,FontSize=26,Alignment=2,"
        f"MarginL=80,MarginR=80,MarginV={margin_v},"
        "BorderStyle=1,Outline=2,Shadow=0,"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000"
    )
    return (
        f"drawbox=x=0:y=ih-{band}:w=iw:h={band}:color=black@0.82:t=fill,"
        f"subtitles=filename='{_escape_filter_path(srt)}':charenc=UTF-8:force_style='{style}'"
    )


def assemble_recording(
    webm: Path,
    lead_s: float,
    steps: list[tuple[Path, Path, int]],
    out: Path,
    *,
    fps: int,
    threads: int,
) -> None:
    """Trim a recordVideo webm to the hold window and lay the measured audio under it.

    ``steps`` is ``(png, wav, frame_count)``. The PNGs are unused; the wavs and
    frame counts are the audio timeline. A short or long picture raises
    SyncError so the caller can fall back to stills.
    """
    timeline = sum(frames / fps for _png, _wav, frames in steps)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    args: list[str] = [
        _ffmpeg(), "-y", "-threads", str(threads),
        "-i", str(webm),
    ]
    filters = [
        f"[0:v]fps={fps},format=yuv420p,trim=start={lead_s:.6f}:duration={timeline:.6f},"
        f"setpts=PTS-STARTPTS[v]"
    ]
    for index, (_png, wav, frames) in enumerate(steps):
        seconds = frames / fps
        args.extend(["-i", str(wav)])
        filters.append(
            f"[{index + 1}:a]aresample=48000,"
            f"apad=whole_dur={seconds:.6f},atrim=0:{seconds:.6f},"
            f"asetpts=PTS-STARTPTS[a{index}]"
        )
    audio = "".join(f"[a{i}]" for i in range(len(steps)))
    filters.append(f"{audio}concat=n={len(steps)}:v=0:a=1[a]")
    args.extend([
        "-filter_complex", ";".join(filters),
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-c:a", "aac",
        "-b:a", "160k",
        "-ac", "1",
        "-t", f"{timeline:.6f}",
        "-threads", str(threads),
        "-movflags", "+faststart",
        str(out),
    ])
    _run(args)
    assert_av_sync(out, timeline)


def add_subtitles(
    video: Path,
    srt: Path,
    out: Path,
    *,
    burn_in: bool,
    threads: int,
    subtitle_band: int = DEFAULT_SUBTITLE_BAND,
) -> None:
    """Embed ``srt`` as a mov_text track. With burn_in, also draw it in the bottom band."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    picture = video
    if burn_in:
        burned = out.with_suffix(".burned.mp4")
        _run([
            _ffmpeg(), "-y",
            "-i", str(video),
            "-vf", burn_in_filter(srt, subtitle_band),
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
            "-show_entries",
            "format=duration:stream=index,codec_type,codec_name,codec_tag_string,width,height,duration",
            "-of", "json",
            str(path),
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    import json
    return json.loads(completed.stdout)
