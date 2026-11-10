"""Generate an editable frontend-slides scaffold from an approved handoff.

This is intentionally an authoring scaffold, not a release-ready presentation.
It carries reviewed science, reasoning structure, audience wording, semantic
cues, and visual intent into the primary slide engine. A person or authoring
agent is still expected to replace visual-intent placeholders with real
figures, diagrams, plots, or animation before visual QA and release review.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

from checks.authoring import AuthoringError, verify_handoff
from checks.yamldump import dumps as dump_yaml
from slides.cues import CueMapError, load_cue_map
from video.deck import load_deck, walk_states

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = (
    ROOT
    / "upstream"
    / "frontend-slides-PKU"
    / "assets"
    / "templates"
    / "Empty_template.html"
)
_INSERT_MARKER = "<!-- END slides-scroller -->"
_SAFE_CUE = re.compile(r"^[A-Za-z0-9_.:-]+$")


class ScaffoldError(ValueError):
    """The approved handoff cannot be converted into a safe slide scaffold."""


def generate_scaffold(
    handoff_path: Path,
    out_dir: Path,
    *,
    template_path: Path | None = None,
    title: str | None = None,
    author: str = "",
    event: str = "",
    voice: str = "af_sarah",
) -> dict[str, object]:
    try:
        handoff = verify_handoff(handoff_path)
    except AuthoringError as exc:
        raise ScaffoldError(str(exc)) from exc

    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    template_path = (
        Path(template_path).resolve()
        if template_path is not None
        else DEFAULT_TEMPLATE.resolve()
    )
    if not template_path.is_file():
        raise ScaffoldError(
            f"frontend-slides template not found: {template_path}. "
            "Initialize the submodule or pass --template."
        )
    template = template_path.read_text(encoding="utf-8")
    if _INSERT_MARKER not in template:
        raise ScaffoldError(
            f"{template_path}: missing insertion marker {_INSERT_MARKER!r}"
        )

    brief = handoff.get("brief")
    default_title = "HEP explainer authoring scaffold"
    if isinstance(brief, dict) and brief.get("topic"):
        default_title = str(brief["topic"])
    deck_title = (title or default_title).strip()
    if not deck_title:
        raise ScaffoldError("title must not be empty")

    raw_scenes = handoff.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ScaffoldError("handoff has no scenes")

    sections: list[str] = []
    narration_steps: list[dict[str, object]] = []
    plan_scenes: list[dict[str, object]] = []
    for slide_number, raw_scene in enumerate(raw_scenes, 1):
        if not isinstance(raw_scene, dict):
            raise ScaffoldError(f"scene {slide_number} is malformed")
        section, steps, plan = _scene_section(raw_scene, slide_number)
        sections.append(section)
        narration_steps.extend(steps)
        plan_scenes.append(plan)

    deck_html = template
    replacements = {
        "{{TITLE_PLACEHOLDER}}": html.escape(deck_title),
        "{{AUTHOR_PLACEHOLDER}}": html.escape(author),
        "{{EVENT_PLACEHOLDER}}": html.escape(event),
    }
    for token, value in replacements.items():
        deck_html = deck_html.replace(token, value)
    deck_html = deck_html.replace(
        _INSERT_MARKER,
        "\n".join(sections) + "\n            " + _INSERT_MARKER,
        1,
    )

    deck_path = out_dir / "deck.html"
    narration_path = out_dir / "narration.yaml"
    plan_path = out_dir / "scaffold-plan.json"
    deck_path.write_text(deck_html, encoding="utf-8")
    narration_path.write_text(
        dump_yaml({
            "title": deck_title,
            "voice": voice,
            "lang": "en-us",
            "pad_seconds": 0.35,
            "steps": narration_steps,
        }),
        encoding="utf-8",
    )

    cue_map = load_cue_map(deck_path)
    resolved = [
        cue_map.resolve(str(item["scene"]), str(item["cue"]))
        for item in narration_steps
    ]
    states = walk_states(load_deck(deck_path))
    if resolved != states:
        raise ScaffoldError(
            "generated semantic narration does not match the frontend slide walk: "
            f"narration={resolved}, deck={states}"
        )

    plan = {
        "schema_version": 1,
        "kind": "reviewed_slide_authoring_scaffold",
        "handoff": str(Path(handoff_path).resolve()),
        "handoff_payload_sha256": handoff["payload_sha256"],
        "template": str(template_path),
        "title": deck_title,
        "author": author,
        "event": event,
        "voice": voice,
        "deck": str(deck_path),
        "narration": str(narration_path),
        "states": [
            {
                "slide": slide,
                "step": step,
                "scene": narration_steps[index]["scene"],
                "cue": narration_steps[index]["cue"],
            }
            for index, (slide, step) in enumerate(resolved)
        ],
        "scenes": plan_scenes,
        "release_ready": False,
        "next_checks": [
            "Replace visual-intent placeholders with authored scientific visuals.",
            "Run slide cue parity and visual QA.",
            "Run the normal scientific release review before publication.",
        ],
    }
    plan_path.write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return plan


def _scene_section(
    scene: dict[str, object],
    slide_number: int,
) -> tuple[str, list[dict[str, object]], dict[str, object]]:
    scene_id = str(scene.get("id") or "").strip()
    if not scene_id or not _SAFE_CUE.fullmatch(scene_id):
        raise ScaffoldError(
            f"scene {slide_number}: id must match {_SAFE_CUE.pattern}"
        )
    question = str(scene.get("question") or "").strip()
    takeaway = str(scene.get("takeaway") or "").strip()
    visual_purpose = str(scene.get("visual_purpose") or "").strip()
    if not question or not takeaway or not visual_purpose:
        raise ScaffoldError(
            f"{scene_id}: question, takeaway, and visual_purpose are required"
        )

    raw_narration = scene.get("narration")
    if not isinstance(raw_narration, list) or not raw_narration:
        raise ScaffoldError(f"{scene_id}: handoff narration must be a non-empty list")

    cue_names: list[str] = []
    narration_steps: list[dict[str, object]] = []
    for index, raw_segment in enumerate(raw_narration):
        if not isinstance(raw_segment, dict):
            raise ScaffoldError(f"{scene_id}: narration segment {index + 1} is malformed")
        raw_cue = str(raw_segment.get("cue") or "").strip()
        if raw_cue:
            if not _SAFE_CUE.fullmatch(raw_cue):
                raise ScaffoldError(
                    f"{scene_id}: cue {raw_cue!r} must match {_SAFE_CUE.pattern}"
                )
            cue = raw_cue
        else:
            cue = "base" if index == 0 else f"segment-{index + 1}"
        if cue in cue_names:
            raise ScaffoldError(f"{scene_id}: duplicate scaffold cue {cue}")
        text = str(raw_segment.get("text") or "").strip()
        if not text:
            raise ScaffoldError(f"{scene_id}/{cue}: narration text is empty")
        cue_names.append(cue)
        narration_steps.append({
            "scene": scene_id,
            "cue": cue,
            "text": text,
        })

    raw_claims = scene.get("claims") or []
    if not isinstance(raw_claims, list):
        raise ScaffoldError(f"{scene_id}: claims must be a list")
    audience_points: list[str] = []
    claim_refs: list[str] = []
    for raw_claim in raw_claims:
        if not isinstance(raw_claim, dict):
            continue
        ref = str(raw_claim.get("claim_ref") or "").strip()
        wording = str(raw_claim.get("audience_wording") or "").strip()
        if ref:
            claim_refs.append(ref)
        if wording:
            audience_points.append(wording)

    max_step = len(cue_names) - 1
    bullet_html: list[str] = []
    if not audience_points:
        bullet_html.append(
            "<li>Replace this placeholder with the reviewed audience-specific point.</li>"
        )
    else:
        for index, point in enumerate(audience_points):
            if index == 0 or max_step == 0:
                attrs = ""
            else:
                step = min(index, max_step)
                attrs = f' class="st pop" data-st="{step}"'
            bullet_html.append(
                f"<li{attrs}>{html.escape(point)}</li>"
            )

    cue_stage_html = [
        (
            '<div class="highlight-box" style="margin-bottom:16px;">'
            f"<b>Visual intent:</b> {html.escape(visual_purpose)}"
            "</div>"
        )
    ]
    for step, cue in enumerate(cue_names[1:], 1):
        cue_stage_html.append(
            f'<div class="st pop tip-box" data-st="{step}" '
            f'data-cue="{html.escape(cue)}" style="margin-top:12px;">'
            f"<b>Author visual action for cue {html.escape(cue)}:</b> "
            "replace this placeholder with the corresponding figure, diagram, "
            "plot, highlight, or animation state."
            "</div>"
        )

    method_html = _method_validation_html(scene.get("method_validation"))
    first_cue = cue_names[0]
    section = f"""
<section class="slide normal-slide"
         data-header="visible"
         data-title="{html.escape(question)}"
         data-scene="{html.escape(scene_id)}"
         data-cue="{html.escape(first_cue)}">
  <div class="slide-content">
    <div style="font-size:18px;letter-spacing:.08em;text-transform:uppercase;opacity:.65;margin-bottom:10px;">
      AUTHORING SCAFFOLD · reviewed science · visual replacement required
    </div>
    <div class="important-box" style="margin-bottom:18px;">
      <b>Takeaway:</b> {html.escape(takeaway)}
    </div>
    <div class="dual-layout" style="--split: 5fr 5fr;">
      <div class="left-col">
        <h3 style="margin-top:0;">Reviewed audience points</h3>
        <ul class="bullet-list">
          {''.join(bullet_html)}
        </ul>
        {method_html}
      </div>
      <div class="right-col">
        {''.join(cue_stage_html)}
      </div>
    </div>
  </div>
</section>
"""

    plan = {
        "slide": slide_number,
        "scene": scene_id,
        "question": question,
        "takeaway": takeaway,
        "visual_purpose": visual_purpose,
        "claim_refs": claim_refs,
        "cues": [
            {"cue": cue, "step": index}
            for index, cue in enumerate(cue_names)
        ],
    }
    return section, narration_steps, plan


def _method_validation_html(raw: object) -> str:
    if not isinstance(raw, dict):
        return ""
    test = html.escape(str(raw.get("test") or ""))
    demonstrates = ", ".join(
        html.escape(str(item))
        for item in raw.get("demonstrates") or []
    )
    limits = ", ".join(
        html.escape(str(item))
        for item in raw.get("does_not_establish") or []
    )
    return (
        '<div class="warning-box" style="margin-top:14px;">'
        "<b>Method-validation boundary</b><br>"
        f"Test: {test}<br>"
        f"Demonstrates: {demonstrates}<br>"
        f"Does not establish: {limits}"
        "</div>"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m slides.scaffold")
    parser.add_argument("handoff", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--template", type=Path)
    parser.add_argument("--title")
    parser.add_argument("--author", default="")
    parser.add_argument("--event", default="")
    parser.add_argument("--voice", default="af_sarah")
    args = parser.parse_args(argv)
    try:
        plan = generate_scaffold(
            args.handoff,
            args.out_dir,
            template_path=args.template,
            title=args.title,
            author=args.author,
            event=args.event,
            voice=args.voice,
        )
        print(
            f"reviewed slide scaffold: {plan['deck']} "
            f"({len(plan['states'])} narrated state(s)); release_ready=false"
        )
        return 0
    except (
        AuthoringError,
        ScaffoldError,
        CueMapError,
        OSError,
        ValueError,
    ) as exc:
        print(f"slide scaffold: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
