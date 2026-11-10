"""Record the deck. recordVideo is tried once; a dead browser falls back to stills.

Per-step screenshots plus ffmpeg (in mux.py) are the path that keeps each
on-screen hold equal to the measured audio duration. recordVideo sleeps for
that same duration, but a killed Chromium used to abort the whole render.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
from pathlib import Path

RECORD_SCRIPT = Path(__file__).resolve().parent / "record-deck.mjs"
VIDEO_DIR = RECORD_SCRIPT.parent


class RecorderAbort(RuntimeError):
    """Playwright recordVideo did not finish. The stills path can take over."""


def _require_playwright() -> None:
    if not (VIDEO_DIR / "node_modules" / "playwright").is_dir():
        raise SystemExit(
            "Playwright is not installed. From the repo root:\n"
            "  npm --prefix video install\n"
            "  npx --prefix video playwright install chromium"
        )


def _run_node(plan: dict, timeout: float) -> subprocess.CompletedProcess[str]:
    plan_path = Path(plan["plan_path"])
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    proc = subprocess.Popen(
        ["node", str(RECORD_SCRIPT), str(plan_path)],
        cwd=VIDEO_DIR,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        # SIGTERM first so the recorder can context.close(). Playwright writes
        # a 0-byte webm until that close; SIGKILL skips it.
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            stdout, stderr = proc.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            stdout, stderr = proc.communicate()
        raise RecorderAbort(
            f"recorder timed out after {timeout:.0f}s; "
            "fell back after asking it to close the browser context"
        ) from exc
    completed = subprocess.CompletedProcess(proc.args, proc.returncode or 0, stdout, stderr)
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.returncode != 0:
        if completed.stderr:
            print(completed.stderr)
        blob = (completed.stderr or "") + (completed.stdout or "")
        hint = ""
        if "Executable doesn't exist" in blob or "browserType.launch" in blob:
            hint = " Install the browser: npx --prefix video playwright install chromium"
        raise RecorderAbort(f"recorder exited {completed.returncode}.{hint}")
    return completed


def _shot_plan(deck_html: Path, shots: list[tuple[int, int, Path]], holds: list[float]) -> list[dict]:
    planned = []
    for (slide, step, png), hold in zip(shots, holds):
        planned.append({
            "slide": slide,
            "step": step,
            "png": str(png),
            "holdMs": max(0, int(round(hold * 1000))),
        })
    return planned


def record_stills(
    deck_html: Path,
    shots: list[tuple[int, int, Path]],
    holds: list[float],
    work: Path,
) -> None:
    """One PNG per step. Retries the walk if Chromium is killed."""
    _require_playwright()
    plan = {
        "mode": "stills",
        "deck": str(deck_html),
        "plan_path": str(work / "record-plan.json"),
        "shots": _shot_plan(deck_html, shots, holds),
    }
    last_error: Exception | None = None
    for attempt in range(1, 3):
        try:
            _run_node(plan, timeout=120 + 15 * len(shots))
            return
        except RecorderAbort as exc:
            last_error = exc
            print(f"screenshot walk attempt {attempt} aborted: {exc}")
            for _slide, _step, png in shots:
                if png.exists() and png.stat().st_size < 8000:
                    png.unlink()
    raise RecorderAbort(f"per-step screenshots failed: {last_error}")


def record_video(
    deck_html: Path,
    shots: list[tuple[int, int, Path]],
    holds: list[float],
    work: Path,
) -> tuple[Path, float]:
    """Return ``(webm, lead_seconds)``. Raises RecorderAbort if the browser dies."""
    _require_playwright()
    video_dir = work / "record-video"
    video_dir.mkdir(parents=True, exist_ok=True)
    plan = {
        "mode": "video",
        "deck": str(deck_html),
        "videoDir": str(video_dir),
        "plan_path": str(work / "record-video-plan.json"),
        "shots": _shot_plan(deck_html, shots, holds),
    }
    timeout = sum(holds) + 30
    try:
        completed = _run_node(plan, timeout=timeout)
    except RecorderAbort:
        raise
    lead_ms = None
    video = None
    for line in (completed.stdout or "").splitlines():
        if line.startswith("LEAD_MS "):
            lead_ms = int(line.split()[1])
        elif line.startswith("VIDEO "):
            video = Path(line.split(" ", 1)[1].strip())
    empties = [path for path in video_dir.glob("*.webm") if path.stat().st_size < 1000]
    if lead_ms is None or video is None or not video.is_file() or video.stat().st_size < 1000:
        empty_note = ""
        if empties:
            empty_note = " Empty webm files: " + ", ".join(str(path) for path in empties) + "."
        raise RecorderAbort(
            "recordVideo did not finalize a video. Playwright only writes the "
            f"webm when the browser context is closed.{empty_note}"
        )
    return video, lead_ms / 1000


def capture(
    deck_html: Path,
    shots: list[tuple[int, int, Path]],
    holds: list[float],
    work: Path,
    *,
    mode: str = "auto",
) -> dict:
    """Capture pictures.

    ``auto`` tries recordVideo once. An abort, timeout, or missing file falls
    back to per-step screenshots. The caller still has to check that a
    recordVideo timeline matches the audio within 0.2s and fall back again
    if it drifted.
    """
    if mode not in {"auto", "video", "stills"}:
        raise SystemExit(f"unknown capture mode {mode!r}")
    if mode != "stills":
        try:
            webm, lead = record_video(deck_html, shots, holds, work)
            return {"mode": "video", "webm": webm, "lead": lead}
        except RecorderAbort as exc:
            if mode == "video":
                raise SystemExit(f"recordVideo aborted: {exc}") from exc
            print(f"recordVideo aborted ({exc}); falling back to per-step screenshots")
    print("recording per-step screenshots")
    record_stills(deck_html, shots, holds, work)
    return {"mode": "stills"}
