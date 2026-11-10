"""Capture every live-deck reveal state and build a self-contained QA contact sheet."""

from __future__ import annotations

import argparse
import base64
import html
import json
import sys
from pathlib import Path

from video.deck import load_deck, walk_states
from video.record import RecorderAbort, record_stills


def resolve_html(deck: Path) -> Path:
    deck = Path(deck)
    if deck.is_file():
        return deck.resolve()
    candidate = deck / "deck.html"
    if candidate.is_file():
        return candidate.resolve()
    htmls = sorted(deck.glob("*.html"))
    if len(htmls) == 1:
        return htmls[0].resolve()
    raise ValueError(f"{deck}: expected deck.html or exactly one HTML file")


def capture_qa(deck: Path, out: Path, work: Path | None = None) -> dict:
    html_path = resolve_html(deck)
    states = walk_states(load_deck(html_path))
    out = Path(out)
    if work is None:
        work = out.parent / f"{out.stem}-work"
    work = Path(work)
    frames = work / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    shots = [
        (slide, step, frames / f"s{slide:02d}-st{step:02d}.png")
        for slide, step in states
    ]
    record_stills(html_path, shots, [0.05] * len(shots), work)
    qa_path = work / "render-qa.json"
    data = json.loads(qa_path.read_text(encoding="utf-8"))
    by_state = {
        (int(row["slide"]), int(row["step"])): row
        for row in data.get("states") or []
    }
    rows = []
    issue_count = 0
    for slide, step, png in shots:
        finding = by_state.get((slide, step), {})
        issues = _issues(finding)
        issue_count += len(issues)
        rows.append({
            "slide": slide,
            "step": step,
            "png": png,
            "finding": finding,
            "issues": issues,
        })
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_contact_sheet(html_path, rows), encoding="utf-8")
    summary = {
        "deck": str(html_path),
        "contact_sheet": str(out),
        "qa_json": str(qa_path),
        "states": len(rows),
        "issues": issue_count,
    }
    out.with_suffix(".json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def _issues(finding: dict) -> list[str]:
    issues: list[str] = []
    if finding and not finding.get("ready", False):
        issues.append("browser content-ready signal was not reached")
    for item in finding.get("brokenImages") or []:
        issues.append(f"broken image: {item}")
    for item in finding.get("overflow") or []:
        issues.append(
            "overflow: "
            + f"{item.get('tag')} .{item.get('class')} "
            + f"[{item.get('left')},{item.get('top')} -> "
            + f"{item.get('right')},{item.get('bottom')}]"
        )
    issues.extend(str(item) for item in finding.get("errors") or [])
    return issues


def _contact_sheet(deck: Path, rows: list[dict]) -> str:
    cards = []
    for row in rows:
        raw = row["png"].read_bytes()
        encoded = base64.b64encode(raw).decode("ascii")
        issues = row["issues"]
        status = "PASS" if not issues else "REVIEW"
        issue_html = "".join(f"<li>{html.escape(item)}</li>" for item in issues)
        cards.append(
            f"""
            <article class="card">
              <h2>Slide {row['slide']} · step {row['step']} · {status}</h2>
              <img src="data:image/png;base64,{encoded}" alt="slide state">
              <ul>{issue_html}</ul>
            </article>
            """
        )
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>HEP slide visual QA</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 24px; background: #f4f4f4; }}
header {{ margin-bottom: 24px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(520px,1fr)); gap: 18px; }}
.card {{ background: white; padding: 14px; border-radius: 10px; box-shadow: 0 2px 10px #0002; }}
.card h2 {{ font-size: 16px; margin: 0 0 10px; }}
.card img {{ width: 100%; border: 1px solid #ccc; }}
.card ul {{ margin-bottom: 0; color: #8a2d00; }}
</style>
</head>
<body>
<header>
<h1>Visual QA contact sheet</h1>
<p>{html.escape(str(deck))}</p>
</header>
<div class="grid">{''.join(cards)}</div>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m video.qa")
    parser.add_argument("deck", type=Path)
    parser.add_argument("--out", type=Path, default=Path("build/deck-qa.html"))
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = capture_qa(args.deck, args.out, args.work_dir)
    except (OSError, ValueError, RecorderAbort, json.JSONDecodeError) as exc:
        print(f"visual QA: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        f"visual QA: {report['states']} states, {report['issues']} issue(s); "
        f"{report['contact_sheet']}"
    )
    return 1 if args.strict and report["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
