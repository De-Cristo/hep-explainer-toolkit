"""Drive the deck in Playwright and write one PNG per step."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

RECORD_SCRIPT = Path(__file__).resolve().parent / "record-deck.mjs"
VIDEO_DIR = RECORD_SCRIPT.parent


def record_frames(deck_html: Path, shots: list[tuple[int, int, Path]]) -> None:
    """``shots`` is (slide, step, png) in walk order."""
    if not (VIDEO_DIR / "node_modules" / "playwright").is_dir():
        raise SystemExit(
            "Playwright is not installed. From the repo root:\n"
            "  npm --prefix video install\n"
            "  npx --prefix video playwright install chromium"
        )
    plan = {
        "deck": str(deck_html),
        "shots": [
            {"slide": slide, "step": step, "png": str(png)}
            for slide, step, png in shots
        ],
    }
    plan_path = shots[0][2].parent / "record-plan.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    completed = subprocess.run(
        ["node", str(RECORD_SCRIPT), str(plan_path)],
        cwd=VIDEO_DIR,
        text=True,
        capture_output=True,
    )
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.returncode != 0:
        if completed.stderr:
            print(completed.stderr)
        hint = ""
        blob = (completed.stderr or "") + (completed.stdout or "")
        if "Executable doesn't exist" in blob or "browserType.launch" in blob:
            hint = "\nInstall the browser: npx --prefix video playwright install chromium"
        raise SystemExit(f"deck recorder failed (exit {completed.returncode}).{hint}")
