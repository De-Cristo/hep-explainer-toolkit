"""Report which toolkit capabilities are ready on the current machine."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_CAPABILITIES = {
    "checks": ("python",),
    "diagrams": ("pdflatex", "pdftocairo"),
    "slide-video": ("node", "ffmpeg", "ffprobe", "playwright"),
    "theory-video": ("ffmpeg", "ffprobe", "pyyaml", "soundfile"),
    "narrated-theory-video": (
        "ffmpeg",
        "ffprobe",
        "pyyaml",
        "soundfile",
        "kokoro",
        "espeak-ng",
    ),
    "manim": ("ffmpeg", "manim", "latex", "dvisvgm"),
}


def collect_probes() -> dict[str, bool]:
    commands = {
        name: shutil.which(name) is not None
        for name in (
            "node",
            "ffmpeg",
            "ffprobe",
            "pdflatex",
            "pdftocairo",
            "espeak-ng",
            "latex",
            "dvisvgm",
        )
    }
    modules = {
        "pyyaml": importlib.util.find_spec("yaml") is not None,
        "soundfile": importlib.util.find_spec("soundfile") is not None,
        "kokoro": importlib.util.find_spec("kokoro") is not None,
        "manim": importlib.util.find_spec("manim") is not None,
    }
    playwright = (ROOT / "video" / "node_modules" / "playwright").is_dir()
    return {
        "python": sys.version_info >= (3, 10),
        **commands,
        **modules,
        "playwright": playwright,
    }


def evaluate(probes: dict[str, bool]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for capability, requirements in _CAPABILITIES.items():
        missing = [name for name in requirements if not probes.get(name, False)]
        result[capability] = {
            "ready": not missing,
            "requires": list(requirements),
            "missing": missing,
        }
    return result


def format_report(
    probes: dict[str, bool],
    capabilities: dict[str, dict[str, object]],
) -> str:
    lines = ["HEP explainer doctor", ""]
    for name, status in capabilities.items():
        label = "READY" if status["ready"] else "MISSING"
        lines.append(f"{name:24} {label}")
        if status["missing"]:
            lines.append("  missing: " + ", ".join(status["missing"]))
    lines.extend(["", "probes:"])
    for name in sorted(probes):
        lines.append(f"  {name:18} {'yes' if probes[name] else 'no'}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m checks.doctor")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--require",
        action="append",
        choices=sorted(_CAPABILITIES),
        default=[],
        help="fail unless this capability is ready; repeat as needed",
    )
    args = parser.parse_args(argv)
    probes = collect_probes()
    capabilities = evaluate(probes)
    if args.json:
        print(json.dumps({"probes": probes, "capabilities": capabilities}, indent=2))
    else:
        print(format_report(probes, capabilities), end="")
    failed = [
        name for name in args.require
        if not capabilities[name]["ready"]
    ]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
