"""SRT captions from narration blocks and the same clock the video uses."""

from __future__ import annotations

from pathlib import Path


def format_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def wrap_cue(text: str, width: int = 42) -> str:
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = word if not current else f"{current} {word}"
        if len(trial) <= width:
            current = trial
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return "\n".join(lines)


def render_srt(cues: list[tuple[float, float, str]]) -> str:
    """``cues`` is (start_seconds, end_seconds, caption text) in order."""
    blocks: list[str] = []
    for index, (start, end, text) in enumerate(cues, start=1):
        blocks.append(
            f"{index}\n{format_timestamp(start)} --> {format_timestamp(end)}\n{wrap_cue(text)}\n"
        )
    return "\n".join(blocks)


def write_srt(path: Path, cues: list[tuple[float, float, str]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_srt(cues), encoding="utf-8")
