"""Build an integrated human review packet for one explanation scene file."""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

from checks.claims import ClaimRegistryError, load_registry
from checks.review import ReviewError, load_reviews, review_status
from checks.storyboard import (
    StoryboardError,
    check_storyboard,
    narration_segments,
)
from checks.yamlsubset import YamlError, load as load_yaml


class ReleaseError(ValueError):
    """The review packet cannot be built or is not release-ready."""


def build_packet(
    scene_path: Path,
    out: Path,
    *,
    reviews_path: Path | None = None,
    qa_json: Path | None = None,
    public: bool = False,
) -> dict[str, object]:
    scene_path = Path(scene_path).resolve()
    try:
        document = load_yaml(scene_path.read_text(encoding="utf-8"))
    except (OSError, YamlError) as exc:
        raise ReleaseError(f"cannot read scene {scene_path}: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("scenes"), list):
        raise ReleaseError(f"{scene_path}: expected a scenes list")
    registry_raw = str(document.get("claim_registry") or "").strip()
    if not registry_raw:
        raise ReleaseError(f"{scene_path}: release packet needs claim_registry")
    registry_path = (scene_path.parent / registry_raw).resolve()
    try:
        registry = load_registry(registry_path)
        storyboard = check_storyboard(scene_path)
    except (ClaimRegistryError, StoryboardError) as exc:
        raise ReleaseError(str(exc)) from exc

    if public and registry.visibility != "public":
        raise ReleaseError(
            f"{registry.path}: visibility is {registry.visibility}; public packet refused"
        )

    if reviews_path is not None:
        try:
            reviews = load_reviews(reviews_path)
        except ReviewError as exc:
            raise ReleaseError(str(exc)) from exc
    else:
        reviews = {"schema_version": 1, "claims": {}}
    statuses = review_status(registry, reviews)
    used = _used_claims(document)

    qa = None
    if qa_json is not None:
        try:
            qa = json.loads(Path(qa_json).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReleaseError(f"cannot read QA summary {qa_json}: {exc}") from exc

    machine_failures: list[str] = []
    interpretation_failures: list[str] = []
    for claim_id in used:
        claim = registry.get(claim_id)
        if not (
            claim.review["source"] == "declared"
            and claim.review["evidence"] == "retrieved"
            and claim.review["value"] != "pending"
        ):
            machine_failures.append(claim_id)
        if statuses[claim_id] not in {"approved", "embedded_reviewed"}:
            interpretation_failures.append(claim_id)

    review_ready = (
        storyboard.ok
        and not machine_failures
        and not interpretation_failures
        and (qa is None or int(qa.get("issues") or 0) == 0)
    )
    public_validation_error = None
    if public:
        try:
            from checks.explanation import check_explanation
            check_explanation(scene_path)
        except (Exception, SystemExit) as exc:
            public_validation_error = str(exc)
    release_ready = (
        public
        and registry.visibility == "public"
        and review_ready
        and public_validation_error is None
    )

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        _render_html(
            scene_path,
            document,
            registry,
            statuses,
            used,
            storyboard.problems,
            machine_failures,
            interpretation_failures,
            qa,
            review_ready,
            release_ready,
            public_validation_error,
        ),
        encoding="utf-8",
    )
    summary = {
        "scene": str(scene_path),
        "registry": str(registry.path),
        "visibility": registry.visibility,
        "used_claims": used,
        "storyboard_ok": storyboard.ok,
        "machine_failures": machine_failures,
        "interpretation_failures": interpretation_failures,
        "qa_issues": None if qa is None else int(qa.get("issues") or 0),
        "review_ready": review_ready,
        "public_validation_error": public_validation_error,
        "release_ready": release_ready,
        "packet": str(out),
    }
    out.with_suffix(".json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def _used_claims(document: dict) -> list[str]:
    found: list[str] = []
    for scene in document.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        for item in scene.get("claims") or []:
            if isinstance(item, dict) and item.get("claim_ref"):
                ref = str(item["claim_ref"])
                if ref not in found:
                    found.append(ref)
        validation = scene.get("method_validation")
        if isinstance(validation, dict):
            refs = [validation.get("test")]
            refs.extend(validation.get("demonstrates") or [])
            refs.extend(validation.get("does_not_establish") or [])
            for raw in refs:
                ref = str(raw or "").strip()
                if ref and ref not in found:
                    found.append(ref)
    return found


def _scene_local_wording(scene: dict, claim_id: str) -> list[str]:
    values: list[str] = []
    for item in scene.get("claims") or []:
        if not isinstance(item, dict) or str(item.get("claim_ref") or "") != claim_id:
            continue
        text = str(item.get("text") or item.get("tex") or "").strip()
        if text and text not in values:
            values.append(text)
    return values


def _render_html(
    scene_path: Path,
    document: dict,
    registry,
    statuses: dict[str, str],
    used: list[str],
    storyboard_problems: list[str],
    machine_failures: list[str],
    interpretation_failures: list[str],
    qa: dict | None,
    review_ready: bool,
    release_ready: bool,
    public_validation_error: str | None,
) -> str:
    scene_sections: list[str] = []
    for scene in document.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        scene_id = str(scene.get("id") or "?")
        try:
            narration = [segment.text for segment in narration_segments(scene)]
        except StoryboardError:
            narration = []
        validation = scene.get("method_validation")
        validation_html = ""
        if isinstance(validation, dict):
            validation_html = (
                "<h4>Method validation boundary</h4>"
                f"<p><b>Test:</b> {html.escape(str(validation.get('test') or ''))}</p>"
                f"<p><b>Demonstrates:</b> {html.escape(', '.join(str(x) for x in validation.get('demonstrates') or []))}</p>"
                f"<p><b>Does not establish:</b> {html.escape(', '.join(str(x) for x in validation.get('does_not_establish') or []))}</p>"
            )
        scene_sections.append(
            "<section class='scene'>"
            f"<h2>{html.escape(scene_id)} — {html.escape(str(scene.get('question') or ''))}</h2>"
            f"<p><b>Takeaway:</b> {html.escape(str(scene.get('takeaway') or ''))}</p>"
            + "".join(f"<p class='narration'>{html.escape(text)}</p>" for text in narration)
            + validation_html
            + "</section>"
        )

    claim_sections: list[str] = []
    for claim_id in used:
        claim = registry.get(claim_id)
        excerpt = load_yaml(claim.excerpt.read_text(encoding="utf-8"))
        quote = str(excerpt.get("quote") or "") if isinstance(excerpt, dict) else ""
        local_wording: list[str] = []
        for scene in document.get("scenes") or []:
            if isinstance(scene, dict):
                for value in _scene_local_wording(scene, claim_id):
                    if value not in local_wording:
                        local_wording.append(value)
        assumptions = registry.effective_assumptions(claim_id)
        local = "".join(
            f"<li>{html.escape(value)}</li>" for value in local_wording
        ) or "<li>(no audience-specific wording; validation/support claim)</li>"
        claim_sections.append(
            "<section class='claim'>"
            f"<h2>{html.escape(claim_id)}</h2>"
            f"<p><b>Review status:</b> {html.escape(statuses[claim_id])}</p>"
            f"<p><b>Canonical:</b> {html.escape(claim.statement)}</p>"
            f"<p><b>Audience wording:</b></p><ul>{local}</ul>"
            f"<p><b>Citation:</b> {html.escape(_citation(claim.citation))}</p>"
            f"<p><b>Evidence excerpt:</b> {html.escape(quote)}</p>"
            f"<p><b>Effective assumptions:</b> {html.escape('; '.join(assumptions) or '(none)')}</p>"
            f"<p><b>Caveats:</b> {html.escape('; '.join(claim.caveats) or '(none)')}</p>"
            "</section>"
        )

    comparison_sections = []
    for comparison in registry.comparisons:
        relevant = {
            comparison.left,
            comparison.right,
            *comparison.same_when,
            *comparison.differs_when,
        }
        if not relevant.intersection(used):
            continue
        comparison_sections.append(
            "<section class='comparison'>"
            f"<h2>{html.escape(comparison.id)}</h2>"
            f"<p><b>Left:</b> {html.escape(comparison.left)}</p>"
            f"<p><b>Right:</b> {html.escape(comparison.right)}</p>"
            f"<p><b>Same when:</b> {html.escape(', '.join(comparison.same_when))}</p>"
            f"<p><b>Differ when:</b> {html.escape(', '.join(comparison.differs_when))}</p>"
            "</section>"
        )

    failures = []
    failures.extend("storyboard: " + item for item in storyboard_problems)
    failures.extend("machine readiness: " + item for item in machine_failures)
    failures.extend("interpretation review: " + item for item in interpretation_failures)
    if qa is not None and int(qa.get("issues") or 0):
        failures.append(f"visual QA: {int(qa.get('issues') or 0)} issue(s)")
    if public_validation_error:
        failures.append("public renderer validation: " + public_validation_error)
    if release_ready:
        status_html = "<p class='ready'>PUBLIC RELEASE READY</p>"
    elif review_ready:
        status_html = (
            "<p class='ready'>HUMAN REVIEW READY</p>"
            "<p>This packet is not a public release approval.</p>"
        )
    else:
        status_html = (
            "<p class='blocked'>REVIEW REQUIRED</p><ul>"
            + "".join(f"<li>{html.escape(item)}</li>" for item in failures)
            + "</ul>"
        )
    qa_html = ""
    if qa is not None:
        qa_html = (
            "<p><b>Visual QA:</b> "
            f"{html.escape(str(qa.get('states') or '?'))} states, "
            f"{html.escape(str(qa.get('issues') or 0))} issue(s)</p>"
        )

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>HEP explanation review packet</title>
<style>
body {{ font-family: system-ui,sans-serif; max-width: 1100px; margin: 32px auto; padding: 0 20px; line-height: 1.45; }}
section {{ border: 1px solid #ddd; border-radius: 10px; padding: 16px 20px; margin: 16px 0; }}
.claim {{ background: #fafafa; }} .comparison {{ background: #f6f4ff; }}
.ready {{ font-weight: 800; color: #176b2c; }} .blocked {{ font-weight: 800; color: #a12622; }}
.narration {{ padding-left: 14px; border-left: 3px solid #999; }}
code {{ background: #eee; padding: 1px 4px; }}
</style></head><body>
<h1>HEP explanation review packet</h1>
<p><b>Scene:</b> {html.escape(str(scene_path))}</p>
<p><b>Registry visibility:</b> {html.escape(registry.visibility)}</p>
{status_html}
{qa_html}
<h1>Explanation flow</h1>
{''.join(scene_sections)}
<h1>Scientific claims used</h1>
{''.join(claim_sections)}
<h1>Definition comparisons</h1>
{''.join(comparison_sections) or '<p>(none used)</p>'}
</body></html>
"""


def _citation(citation: dict[str, object]) -> str:
    parts = []
    if citation.get("arxiv"):
        parts.append("arXiv:" + str(citation["arxiv"]))
    if citation.get("doi"):
        parts.append("doi:" + str(citation["doi"]))
    if citation.get("local"):
        parts.append("local:" + str(citation["local"]))
    parts.append(str(citation.get("locator") or ""))
    return ", ".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m checks.release")
    parser.add_argument("scene", type=Path)
    parser.add_argument("--out", type=Path, default=Path("build/review.html"))
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--qa-json", type=Path)
    parser.add_argument("--public", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        summary = build_packet(
            args.scene,
            args.out,
            reviews_path=args.reviews,
            qa_json=args.qa_json,
            public=args.public,
        )
    except (ReleaseError, OSError, YamlError) as exc:
        print(f"release packet: FAIL: {exc}", file=sys.stderr)
        return 1
    label = (
        "PUBLIC RELEASE READY"
        if summary["release_ready"]
        else "HUMAN REVIEW READY"
        if summary["review_ready"]
        else "REVIEW REQUIRED"
    )
    print(f"release packet: {label}; {summary['packet']}")
    required_ready = summary["release_ready"] if args.public else summary["review_ready"]
    return 1 if args.strict and not required_ready else 0


if __name__ == "__main__":
    raise SystemExit(main())
