"""Validate the reasoning chain and semantic cues of an explanation scene file."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from checks.brief import BriefError, load_brief
from checks.claims import ClaimRegistry, ClaimRegistryError, load_registry
from checks.citations import load_document, normalize_space, repo_root, resolve_inside
from checks.yamlsubset import YamlError


class StoryboardError(ValueError):
    """The storyboard is incomplete or internally inconsistent."""


@dataclass(frozen=True)
class Segment:
    text: str
    cue: str | None = None


@dataclass
class StoryboardReport:
    scene_file: Path
    audience: str
    learning_goal: str
    rows: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def narration_segments(scene: dict) -> list[Segment]:
    """Return normalized narration segments; a string is one uncued segment."""
    raw = scene.get("narration")
    if isinstance(raw, str):
        text = normalize_space(raw)
        if not text:
            raise StoryboardError(f"{scene.get('id', '?')}: narration is empty")
        return [Segment(text)]
    if not isinstance(raw, list) or not raw:
        raise StoryboardError(
            f"{scene.get('id', '?')}: narration must be text or a non-empty segment list"
        )
    found: list[Segment] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise StoryboardError(
                f"{scene.get('id', '?')}: narration segment {index} must be a mapping"
            )
        text = normalize_space(str(item.get("text") or ""))
        cue = str(item.get("cue") or "").strip()
        if not text:
            raise StoryboardError(
                f"{scene.get('id', '?')}: narration segment {index} has no text"
            )
        if not cue:
            raise StoryboardError(
                f"{scene.get('id', '?')}: segmented narration needs cue on segment {index}"
            )
        if cue in seen:
            raise StoryboardError(
                f"{scene.get('id', '?')}: duplicate narration cue {cue}"
            )
        seen.add(cue)
        found.append(Segment(text, cue))
    return found


def narration_text(scene: dict) -> str:
    return " ".join(segment.text for segment in narration_segments(scene))


def check_storyboard(path: Path) -> StoryboardReport:
    path = Path(path).resolve()
    try:
        document = load_document(path)
    except Exception as exc:
        raise StoryboardError(str(exc)) from exc
    raw_brief = document.get("brief")
    if not raw_brief:
        raise StoryboardError(f"{path}: storyboard needs brief:")
    brief_path = resolve_inside(repo_root(), path.parent, str(raw_brief))
    try:
        brief = load_brief(brief_path)
    except BriefError as exc:
        raise StoryboardError(str(exc)) from exc

    registry = _registry(path, document)
    scenes = document.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise StoryboardError(f"{path}: scenes must be a non-empty list")

    report = StoryboardReport(path, brief.audience_profile, brief.learning_goal)
    known = set(brief.knows)
    introduced: set[str] = set()
    covered: set[str] = set()
    required_distinctions = set(brief.required_distinctions)

    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict) or not scene.get("id"):
            report.problems.append(f"scene {index + 1} needs an id")
            continue
        scene_id = str(scene["id"])
        question = normalize_space(str(scene.get("question") or ""))
        takeaway = normalize_space(str(scene.get("takeaway") or ""))
        visual_purpose = normalize_space(str(scene.get("visual_purpose") or ""))
        if not question:
            report.problems.append(f"{scene_id}: question is required")
        if not takeaway:
            report.problems.append(f"{scene_id}: takeaway is required")
        if not visual_purpose:
            report.problems.append(f"{scene_id}: visual_purpose is required")
        if index < len(scenes) - 1 and not normalize_space(str(scene.get("why_next") or "")):
            report.problems.append(f"{scene_id}: why_next is required before another scene")

        requires = _strings(scene.get("requires"), scene_id, "requires", report)
        missing = [concept for concept in requires if concept not in known]
        if missing:
            report.problems.append(
                f"{scene_id}: requires concepts not yet known: {', '.join(missing)}"
            )

        additions = _strings(scene.get("introduces"), scene_id, "introduces", report)
        repeated = [concept for concept in additions if concept in known]
        if repeated:
            report.problems.append(
                f"{scene_id}: introduces concepts already known: {', '.join(repeated)}"
            )
        introduced.update(additions)
        known.update(additions)

        scene_covered = _strings(
            scene.get("covers_distinctions"),
            scene_id,
            "covers_distinctions",
            report,
        )
        unknown_distinctions = [
            item for item in scene_covered if item not in required_distinctions
        ]
        if unknown_distinctions:
            report.problems.append(
                f"{scene_id}: covers unknown required distinction(s): "
                + "; ".join(unknown_distinctions)
            )
        covered.update(item for item in scene_covered if item in required_distinctions)

        try:
            segments = narration_segments(scene)
        except StoryboardError as exc:
            report.problems.append(str(exc))
            segments = []
        _check_cues(path, scene, segments, report)
        _check_claim_refs(scene_id, scene, registry, report)
        report.rows.append(
            f"{scene_id}: {question or '(no question)'} -> {takeaway or '(no takeaway)'}"
        )

    not_introduced = [item for item in brief.introduce if item not in introduced]
    if not_introduced:
        report.problems.append(
            "brief concepts never introduced: " + ", ".join(not_introduced)
        )
    missing_distinctions = [
        item for item in brief.required_distinctions if item not in covered
    ]
    if missing_distinctions:
        report.problems.append(
            "required distinctions not covered: " + "; ".join(missing_distinctions)
        )
    return report


def format_report(report: StoryboardReport) -> str:
    lines = [
        "# Storyboard review",
        "",
        f"Scene file: {report.scene_file}",
        f"Audience: {report.audience}",
        f"Learning goal: {report.learning_goal}",
        "",
        "## Reasoning sequence",
        "",
    ]
    lines.extend(f"{index + 1}. {row}" for index, row in enumerate(report.rows))
    lines.extend(["", "## Validation", ""])
    if report.problems:
        lines.extend(f"- FAIL: {problem}" for problem in report.problems)
    else:
        lines.append("- PASS: prerequisites, introductions, distinctions, claims, and cues are consistent.")
    return "\n".join(lines).rstrip() + "\n"


def _registry(scene_path: Path, document: dict) -> ClaimRegistry | None:
    raw = document.get("claim_registry")
    if not raw:
        return None
    registry_path = resolve_inside(repo_root(), scene_path.parent, str(raw))
    try:
        return load_registry(registry_path)
    except ClaimRegistryError as exc:
        raise StoryboardError(str(exc)) from exc


def _strings(raw: object, scene_id: str, field: str, report: StoryboardReport) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        report.problems.append(f"{scene_id}: {field} must be a list")
        return []
    values = [normalize_space(str(item)) for item in raw]
    if any(not item for item in values):
        report.problems.append(f"{scene_id}: {field} contains an empty item")
    return [item for item in values if item]


def _check_claim_refs(
    scene_id: str,
    scene: dict,
    registry: ClaimRegistry | None,
    report: StoryboardReport,
) -> None:
    for raw in scene.get("claims") or []:
        if not isinstance(raw, dict):
            continue
        ref = str(raw.get("claim_ref") or "").strip()
        if not ref:
            continue
        if registry is None:
            report.problems.append(
                f"{scene_id}: claim_ref {ref} has no claim_registry"
            )
            continue
        try:
            registry.get(ref)
        except ClaimRegistryError as exc:
            report.problems.append(str(exc))


def _check_cues(
    scene_path: Path,
    scene: dict,
    segments: list[Segment],
    report: StoryboardReport,
) -> None:
    if not segments or all(segment.cue is None for segment in segments):
        return
    visual = scene.get("visual") or {}
    raw_cues = visual.get("cues") or []
    if not isinstance(raw_cues, list) or not raw_cues:
        report.problems.append(
            f"{scene.get('id')}: segmented narration needs visual.cues"
        )
        return
    cues: dict[str, dict] = {}
    for raw in raw_cues:
        if not isinstance(raw, dict) or not raw.get("id"):
            report.problems.append(f"{scene.get('id')}: every visual cue needs an id")
            continue
        cue_id = str(raw["id"])
        if cue_id in cues:
            report.problems.append(f"{scene.get('id')}: duplicate visual cue {cue_id}")
        cues[cue_id] = raw

    used = {segment.cue for segment in segments if segment.cue}
    missing = sorted(cue for cue in used if cue not in cues)
    extra = sorted(cue for cue in cues if cue not in used)
    if missing:
        report.problems.append(
            f"{scene.get('id')}: narration cue(s) have no visual cue: {', '.join(missing)}"
        )
    if extra:
        report.problems.append(
            f"{scene.get('id')}: visual cue(s) are never narrated: {', '.join(extra)}"
        )

    diagram_raw = visual.get("diagram")
    if not diagram_raw:
        return
    diagram_path = resolve_inside(repo_root(), scene_path.parent, str(diagram_raw))
    try:
        diagram = load_document(diagram_path)
    except Exception as exc:
        report.problems.append(str(exc))
        return
    line_ids = {
        str(line.get("id") or "")
        for line in diagram.get("lines") or []
        if isinstance(line, dict)
    }
    for cue_id, cue in cues.items():
        show = cue.get("show_lines")
        if show in (None, "all"):
            continue
        if not isinstance(show, list):
            report.problems.append(
                f"{scene.get('id')}/{cue_id}: show_lines must be a list or all"
            )
            continue
        unknown = [str(item) for item in show if str(item) not in line_ids]
        if unknown:
            report.problems.append(
                f"{scene.get('id')}/{cue_id}: unknown diagram line id(s): "
                + ", ".join(unknown)
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m checks.storyboard")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="validate reasoning and semantic cue flow")
    check.add_argument("scene", type=Path)
    check.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        report = check_storyboard(args.scene)
    except (StoryboardError, YamlError) as exc:
        print(f"storyboard: FAIL: {exc}", file=sys.stderr)
        return 1
    text = format_report(report)
    print(text, end="")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
