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
    parser.add_argument("--burn-in", action="store_true", help="Draw the captions on the picture as well as embedding mov_text")
    parser.add_argument("--threads", type=int, default=4, help="CPU thread cap for Kokoro and ffmpeg (default: 4)")
    parser.add_argument("--pad", type=float, default=None, help="Seconds of silence after each step (overrides the narration file)")
    parser.add_argument("--voice", default=None, help="Kokoro voice (default: af_sarah, or the narration file)")
    parser.add_argument("--speed", type=float, default=None, help="Speech rate, 0.5 to 2.0")
    parser.add_argument(
        "--precision",
        choices=("int8", "fp16", "fp32"),
        default="int8",
        help="Kokoro graph. int8 is the CPU default; fp32 is the full-precision graph (default: int8)",
    )
    parser.add_argument("--model", type=Path, help="Existing Kokoro ONNX file (skips the download)")
    parser.add_argument("--voices", type=Path, help="Existing voices-v1.0.bin (skips the download)")
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
            pad=args.pad,
            voice=args.voice,
            speed=args.speed,
            precision=args.precision,
            model=args.model,
            voices=args.voices,
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
