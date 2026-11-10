"""Check a scene explanation exactly as the renderer will read it, without rendering."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from checks.claims import ClaimRegistryError
from checks.finaltext import FinalTextError, seal_render_job
from checks.renderjob import scene_render_job
from checks.storyboard import (
    StoryboardError,
    check_storyboard,
    format_report as format_storyboard_report,
)
from checks.yamlsubset import YamlError, load as load_yaml


def check_explanation(scene: Path) -> dict[str, object]:
    scene = Path(scene).resolve()
    try:
        document = load_yaml(scene.read_text(encoding="utf-8"))
    except (OSError, YamlError) as exc:
        raise FinalTextError(f"cannot read {scene}: {exc}") from exc
    if not isinstance(document, dict) or not document.get("scenes"):
        raise FinalTextError(f"{scene} needs a non-empty scenes list")

    job = scene_render_job(scene, document)
    seal = seal_render_job(job)
    storyboard_text = None
    if document.get("brief"):
        storyboard = check_storyboard(scene)
        storyboard_text = format_storyboard_report(storyboard)
        if not storyboard.ok:
            raise FinalTextError("storyboard failed:\n" + storyboard_text)
    seal.assert_unchanged()
    return {
        "scene": str(scene),
        "project_root": str(job.root),
        "inputs": len(job.inputs),
        "sealed_files": len(seal.hashes),
        "storyboard": storyboard_text,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m checks.explanation",
        description="Validate the exact scene inputs used by video.explain without rendering.",
    )
    parser.add_argument("scene", type=Path)
    args = parser.parse_args(argv)
    try:
        report = check_explanation(args.scene)
    except (ClaimRegistryError, FinalTextError, StoryboardError, YamlError) as exc:
        print(f"explanation check: FAIL: {exc}", file=sys.stderr)
        return 1
    print("explanation check: PASS")
    print(f"  scene: {report['scene']}")
    print(f"  project root: {report['project_root']}")
    print(f"  explicit inputs: {report['inputs']}")
    print(f"  sealed files: {report['sealed_files']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
