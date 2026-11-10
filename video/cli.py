"""One command: deck folder + narration file -> MP4."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="render-video",
        description="Render a frontend-slides deck and a per-step narration file to an MP4.",
    )
    parser.add_argument(
        "deck",
        type=Path,
        help="Deck folder (deck.html + narration.yaml) or a deck HTML file",
    )
    parser.add_argument("-n", "--narration", type=Path, help="Narration YAML (default: narration.yaml in the deck folder)")
    parser.add_argument("-o", "--out", type=Path, help="Output MP4 (default: <deck>/build/<name>.mp4)")
    parser.add_argument(
        "--burn-in",
        action="store_true",
        help="Also draw captions in a bottom band. The default is a soft mov_text track only, so axis labels stay visible",
    )
    parser.add_argument(
        "--subtitle-band",
        type=int,
        default=180,
        help="Height in pixels of the burned-in caption strip at the bottom of the 1080-tall frame (default: 180)",
    )
    parser.add_argument("--threads", type=int, default=4, help="CPU thread cap for Kokoro and ffmpeg (default: 4)")
    parser.add_argument("--pad", type=float, default=None, help="Seconds of silence after each step (overrides the narration file)")
    parser.add_argument("--voice", default=None, help="Kokoro voice (default: af_sarah, or the narration file)")
    parser.add_argument("--speed", type=float, default=None, help="Speech rate, 0.5 to 2.0")
    parser.add_argument(
        "--capture",
        choices=("auto", "video", "stills"),
        default="auto",
        help="auto tries Playwright recordVideo, then per-step screenshots if that aborts or drifts (default: auto)",
    )
    parser.add_argument("--work-dir", type=Path, help="Where frames and wavs are written")
    parser.add_argument("--check", action="store_true", help="Check the narration against the deck and print the spoken text")
    return parser


def main(argv: list[str] | None = None) -> int:
    # Thread env must be set before onnxruntime is imported. render() does that
    # before constructing the speaker.
    args = build_parser().parse_args(argv)
    from video.pipeline import render

    try:
        render(
            args.deck,
            args.narration,
            args.out,
            threads=args.threads,
            burn_in=args.burn_in,
            subtitle_band=args.subtitle_band,
            pad=args.pad,
            voice=args.voice,
            speed=args.speed,
            capture_mode=args.capture,
            work_dir=args.work_dir,
            check_only=args.check,
        )
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            return 1
        if exc.code in (0, None):
            return 0
        return int(exc.code)
    return 0
