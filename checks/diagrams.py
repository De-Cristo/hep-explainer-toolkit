"""Check a scene file: citations, excerpts, and SM UFO diagrams.

Usage::

    python3 -m checks.diagrams check path/to/scene.yaml
    python3 -m checks.diagrams check path/to/scene.yaml --report build/review.txt

The scene format is documented in ``AGENTS.md``. Diagram vertices are
accepted only when ``checks.ufo_model`` finds them in the vendored
Standard Model UFO. A citation, or a citation whose excerpt was copied
from the diagram, does not bypass that.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from checks.citations import (
    CitationReport,
    Row,
    SceneError,
    diagram_key,
    format_report,
    load_document,
    locator_ok,
    normalize_arxiv,
    normalize_doi,
    normalize_space,
    normalize_tex,
    repo_root,
    resolve_inside,
    valid_arxiv,
    valid_doi,
    vertex_key,
)
from checks.ufo_model import (
    ModelError,
    canonical_token,
    conjugate_token,
    load_model,
    required_arrow,
)
from checks.yamlsubset import YamlError

_DIAGRAM_KINDS = {"diagram", "manim"}
_VISUAL_KINDS = {"slide", "manim", "diagram", "figure", "plot"}
_MOTIONS = {"still", "build"}
_ARROWS = {"with_momentum", "against_momentum", "none"}


def check_path(path: Path) -> CitationReport:
    path = Path(path)
    document = load_document(path)
    scenes = document.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise SceneError(f"{path} needs a non-empty scenes list")
    model = load_model()
    report = CitationReport()
    seen: set[str] = set()
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict) or "id" not in scene:
            raise SceneError(f"scene {index} needs an id")
        scene_id = str(scene["id"])
        if scene_id in seen:
            raise SceneError(f"duplicate scene id {scene_id}")
        seen.add(scene_id)
        _check_scene(report, path, scene_id, scene, model)
    return report


def _check_scene(report: CitationReport, path: Path, scene_id: str, scene: dict, model) -> None:
    narration = normalize_space(str(scene.get("narration") or ""))
    visual = scene.get("visual") or {}
    if not isinstance(visual, dict):
        raise SceneError(f"{scene_id}: visual must be a mapping")
    kind = str(visual.get("kind") or "")
    if kind not in _VISUAL_KINDS:
        raise SceneError(f"{scene_id}: visual.kind must be one of {sorted(_VISUAL_KINDS)}")
    motion = str(visual.get("motion") or "still")
    if motion not in _MOTIONS:
        raise SceneError(f"{scene_id}: visual.motion must be still or build")
    claims = scene.get("claims")
    if not isinstance(claims, list):
        raise SceneError(f"{scene_id}: claims must be a list")

    diagram = _load_diagram(path, visual) if _needs_diagram(visual, kind) else None
    equations = _equations(visual)

    if narration:
        claim_texts = [
            normalize_space(str(item.get("text") or ""))
            for item in claims
            if isinstance(item, dict) and str(item.get("kind") or "") == "claim"
        ]
        if narration not in claim_texts:
            report.add(Row(
                scene_id,
                "narration",
                "FAIL",
                "narration has no claim whose text is the narration",
                narration,
                "",
            ))

    claim_ids: set[str] = set()
    equation_claims: dict[str, str] = {}
    diagram_claims = 0
    for claim in claims:
        if not isinstance(claim, dict) or "id" not in claim:
            raise SceneError(f"{scene_id}: each claim needs an id")
        claim_id = str(claim["id"])
        if claim_id in claim_ids:
            raise SceneError(f"{scene_id}: duplicate claim id {claim_id}")
        claim_ids.add(claim_id)
        claim_kind = str(claim.get("kind") or "")
        if claim_kind not in {"claim", "equation", "diagram"}:
            raise SceneError(f"{scene_id}/{claim_id}: kind must be claim, equation, or diagram")
        if claim_kind == "equation":
            equation_claims[claim_id] = str(claim.get("tex") or claim.get("text") or "")
        if claim_kind == "diagram":
            diagram_claims += 1
        _check_claim(report, path, scene_id, claim, narration, diagram, model)

    if diagram is not None and diagram_claims == 0:
        report.add(Row(
            scene_id,
            "diagram",
            "FAIL",
            "diagram has no claim of kind diagram",
            _vertex_block(diagram["vertices"]),
            "",
        ))
    for equation in equations:
        tex = equation_claims.get(equation["id"])
        if tex is None or normalize_tex(tex) != normalize_tex(equation["tex"]):
            report.add(Row(
                scene_id,
                equation["id"],
                "FAIL",
                "equation has no claim of kind equation with the same tex",
                equation["tex"],
                "",
            ))
    if diagram is not None:
        _check_drawing(report, scene_id, diagram, model)


def _needs_diagram(visual: dict, kind: str) -> bool:
    if kind in _DIAGRAM_KINDS:
        return True
    return "diagram" in visual or "spec" in visual


def _equations(visual: dict) -> list[dict[str, str]]:
    raw = visual.get("equations") or []
    if not isinstance(raw, list):
        raise SceneError("visual.equations must be a list")
    found = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict) or "id" not in item or "tex" not in item:
            raise SceneError(f"equation {index} needs id and tex")
        found.append({"id": str(item["id"]), "tex": str(item["tex"])})
    return found


def load_diagram(path: Path) -> dict:
    """Load a standalone diagram file. The path must stay inside the repository."""
    path = Path(path)
    return _load_diagram(path, {"diagram": path.name})


def _load_diagram(scene_path: Path, visual: dict) -> dict:
    if "spec" in visual:
        data = visual["spec"]
        if not isinstance(data, dict):
            raise SceneError("visual.spec must be a mapping")
    elif "diagram" in visual:
        diagram_path = resolve_inside(repo_root(), scene_path.parent, str(visual["diagram"]))
        if not diagram_path.is_file():
            raise SceneError(f"diagram file not found: {visual['diagram']}")
        data = load_document(diagram_path)
    else:
        raise SceneError("diagram visual needs diagram: or spec:")
    vertices = [_vertex_legs(entry) for entry in data.get("vertices") or []]
    if not vertices:
        raise SceneError("diagram needs a vertices list")
    lines = []
    for entry in data.get("lines") or []:
        if not isinstance(entry, dict) or "particle" not in entry:
            raise SceneError("each diagram line needs a particle")
        lines.append(entry)
    return {
        "vertices": vertices,
        "lines": lines,
        "positions": data.get("positions") or data.get("at") or {},
        "raw": data,
    }


def _vertex_legs(entry: object) -> list[str]:
    if isinstance(entry, list):
        return [str(leg) for leg in entry]
    if isinstance(entry, dict):
        legs = entry.get("particles")
        if legs is None:
            legs = entry.get("legs")
        if isinstance(legs, list):
            return [str(leg) for leg in legs]
    raise SceneError(f"vertex must be a list of particles or a mapping with particles: {entry!r}")


def _check_claim(
    report: CitationReport,
    scene_path: Path,
    scene_id: str,
    claim: dict,
    narration: str,
    diagram: dict | None,
    model,
) -> None:
    claim_id = str(claim["id"])
    kind = str(claim["kind"])
    citation = claim.get("citation")
    item_body = _claim_body(claim, kind, narration, diagram)
    if not isinstance(citation, dict):
        report.add(Row(
            scene_id, claim_id, "FAIL",
            "no citation (arxiv or doi, plus a locator)",
            item_body, "",
        ))
        return
    problems = _citation_problems(citation)
    excerpt_raw = claim.get("excerpt")
    if not excerpt_raw:
        problems.append("no excerpt path")
    if problems:
        report.add(Row(
            scene_id, claim_id, "FAIL",
            "; ".join(problems),
            item_body, "",
        ))
        return
    try:
        excerpt_path = resolve_inside(repo_root(), scene_path.parent, str(excerpt_raw))
    except SceneError as exc:
        report.add(Row(scene_id, claim_id, "FAIL", str(exc), item_body, ""))
        return
    if not excerpt_path.is_file():
        report.add(Row(
            scene_id, claim_id, "FAIL",
            f"excerpt file not found: {excerpt_raw}",
            item_body, "",
        ))
        return
    try:
        excerpt = load_document(excerpt_path)
    except SceneError as exc:
        report.add(Row(scene_id, claim_id, "FAIL", str(exc), item_body, ""))
        return
    quote = str(excerpt.get("quote") or "")
    mismatch = _excerpt_identity(citation, excerpt)
    if len(normalize_space(quote)) < _MIN_QUOTE_LEN():
        mismatch.append(f"excerpt quote is missing or shorter than {_MIN_QUOTE_LEN()} characters")
    if kind == "equation":
        tex = str(claim.get("tex") or claim.get("text") or "")
        if normalize_tex(tex) not in normalize_tex(quote):
            mismatch.append("equation does not appear in the excerpt quote")
    if kind == "diagram":
        if diagram is None:
            mismatch.append("diagram claim but the scene visual has no diagram")
        else:
            listed = excerpt.get("vertices")
            if not isinstance(listed, list) or not listed:
                mismatch.append("excerpt has no vertex list to compare with the diagram")
            else:
                try:
                    excerpt_vertices = [_vertex_legs(entry) for entry in listed]
                except SceneError as exc:
                    mismatch.append(str(exc))
                    excerpt_vertices = []
                if excerpt_vertices and diagram_key(diagram["vertices"]) != diagram_key(excerpt_vertices):
                    mismatch.append(
                        "diagram vertices do not match the excerpt vertex list\n"
                        f"diagram: {diagram_key(diagram['vertices'])}\n"
                        f"excerpt: {diagram_key(excerpt_vertices)}"
                    )
    excerpt_body = _excerpt_body(excerpt)
    if mismatch:
        report.add(Row(
            scene_id, claim_id, "FAIL",
            "; ".join(mismatch),
            item_body, excerpt_body,
        ))
        return
    report.add(Row(
        scene_id, claim_id, "PASS",
        _pass_note(kind),
        item_body, excerpt_body,
    ))


def _MIN_QUOTE_LEN() -> int:
    from checks.citations import _MIN_QUOTE
    return _MIN_QUOTE


def _claim_body(claim: dict, kind: str, narration: str, diagram: dict | None) -> str:
    if kind == "equation":
        return str(claim.get("tex") or claim.get("text") or "")
    if kind == "diagram" and diagram is not None:
        return _vertex_block(diagram["vertices"])
    text = claim.get("text")
    if text in (None, ""):
        return narration
    return str(text)


def _vertex_block(vertices: list[list[str]]) -> str:
    lines = []
    for legs in vertices:
        lines.append("[" + ", ".join(str(leg) for leg in legs) + "]")
    return "\n".join(lines)


def _excerpt_body(excerpt: dict) -> str:
    parts = [str(excerpt.get("quote") or "").rstrip()]
    vertices = excerpt.get("vertices")
    if isinstance(vertices, list) and vertices:
        try:
            rendered = [_vertex_legs(entry) for entry in vertices]
        except SceneError:
            rendered = []
        if rendered:
            parts.append("vertices:")
            parts.append(_vertex_block(rendered))
    return "\n".join(parts)


def _citation_problems(citation: dict) -> list[str]:
    problems = []
    arxiv = str(citation.get("arxiv") or "")
    doi = str(citation.get("doi") or "")
    if not arxiv and not doi:
        problems.append("citation needs an arxiv id or a doi")
    if arxiv and not valid_arxiv(arxiv):
        problems.append(f"arxiv id {arxiv!r} is not NNNN.NNNNN or an old-style archive id")
    if doi and not valid_doi(doi):
        problems.append(f"doi {doi!r} does not look like 10.xxxx/...")
    locator = str(citation.get("locator") or "")
    if not locator_ok(locator):
        problems.append("locator must name an equation, section, or figure number")
    return problems


def _excerpt_identity(citation: dict, excerpt: dict) -> list[str]:
    problems = []
    if citation.get("arxiv"):
        if normalize_arxiv(str(citation["arxiv"])) != normalize_arxiv(str(excerpt.get("arxiv") or "")):
            problems.append("excerpt arxiv does not match the citation")
    elif excerpt.get("arxiv"):
        problems.append("excerpt cites an arxiv id the claim does not")
    if citation.get("doi") or excerpt.get("doi"):
        if normalize_doi(str(citation.get("doi") or "")) != normalize_doi(str(excerpt.get("doi") or "")):
            problems.append("excerpt doi does not match the citation")
    if normalize_space(str(citation.get("locator") or "")) != normalize_space(str(excerpt.get("locator") or "")):
        problems.append("excerpt locator does not match the citation")
    return problems


def _pass_note(kind: str) -> str:
    if kind == "equation":
        return "equation appears in the excerpt quote"
    if kind == "diagram":
        return "excerpt vertex list matches the diagram; model check is separate"
    return "excerpt is stored for the same arxiv/doi and locator"


def resolve_drawing(diagram: dict, model=None) -> dict:
    """Fill fermion arrows the way the renderer will draw them.

    An omitted arrow becomes the fermion-flow arrow. An explicit arrow is
    kept, so a flipped antifermion arrow is what both the picture and the
    check see.
    """
    model = model or load_model()
    lines = []
    for line in diagram["lines"]:
        particle = str(line["particle"])
        arrow = line.get("arrow")
        if arrow in (None, ""):
            expected = required_arrow(particle, model)
            arrow = expected if expected is not None else "none"
        lines.append({
            "id": str(line.get("id") or particle),
            "particle": particle,
            "source": None if line.get("source") is None else str(line.get("source")),
            "target": None if line.get("target") is None else str(line.get("target")),
            "arrow": str(arrow),
        })
    positions = diagram.get("positions") or {}
    return {"vertices": diagram["vertices"], "lines": lines, "positions": positions}


def _check_drawing(report: CitationReport, scene_id: str, diagram: dict, model) -> None:
    try:
        drawing = resolve_drawing(diagram, model)
    except ModelError as exc:
        report.add(Row(scene_id, "diagram", "FAIL", str(exc), "", ""))
        return
    lines = drawing["lines"]
    crossed: dict[str, list[str]] = {}
    if lines:
        touched: dict[str, list[str]] = {}
        known = set()
        for vertex in diagram["raw"].get("vertices") or []:
            if isinstance(vertex, dict) and vertex.get("id"):
                known.add(str(vertex["id"]))
        for line in lines:
            particle = line["particle"]
            arrow = line["arrow"]
            if arrow not in _ARROWS:
                report.add(Row(
                    scene_id, str(line.get("id") or particle), "FAIL",
                    f"arrow {arrow!r} is not with_momentum, against_momentum, or none",
                    particle, "",
                ))
                continue
            try:
                expected = required_arrow(particle, model)
            except ModelError as exc:
                report.add(Row(scene_id, str(line.get("id") or particle), "FAIL", str(exc), particle, ""))
                continue
            line_id = str(line.get("id") or particle)
            if expected is None:
                if arrow != "none":
                    report.add(Row(
                        scene_id, line_id, "FAIL",
                        f"{particle} is not a fermion; it cannot carry a fermion arrow ({arrow})",
                        f"{particle} arrow={arrow}", "",
                    ))
            elif arrow != expected:
                report.add(Row(
                    scene_id, line_id, "FAIL",
                    f"{particle} arrow is {arrow}; the SM fermion-flow rule requires {expected}",
                    f"{particle} arrow={arrow}",
                    f"required {expected}",
                ))
            for endpoint, end in (("source", line.get("source")), ("target", line.get("target"))):
                if end is None:
                    continue
                end_s = str(end)
                if known and end_s in known:
                    touched.setdefault(end_s, []).append(canonical_token(particle))
                    # source -> target is the physical momentum direction. At a
                    # source vertex the state is outgoing and must be crossed
                    # to its conjugate for the UFO all-incoming convention.
                    ufo_particle = particle if endpoint == "target" else conjugate_token(particle, model)
                    crossed.setdefault(end_s, []).append(ufo_particle)
        if known:
            for vertex in diagram["raw"]["vertices"]:
                if not isinstance(vertex, dict) or "id" not in vertex:
                    continue
                vid = str(vertex["id"])
                legs = _vertex_legs(vertex)
                got = tuple(sorted(touched.get(vid, [])))
                want = vertex_key(legs)
                if got != want:
                    report.add(Row(
                        scene_id, vid, "FAIL",
                        "lines meeting this vertex do not match its particle list",
                        f"lines {list(got)}",
                        f"vertex {list(want)}",
                    ))
    raw_vertices = diagram["raw"].get("vertices") or []
    for index, vertex in enumerate(raw_vertices, start=1):
        legs = _vertex_legs(vertex)
        check_legs = legs
        crossed_note = ""
        if isinstance(vertex, dict) and vertex.get("id"):
            vid = str(vertex["id"])
            directed = crossed.get(vid) or []
            if len(directed) == len(legs):
                check_legs = directed
                crossed_note = " after crossing outgoing physical lines to the UFO all-incoming convention"
        try:
            verdict = model.allows(check_legs)
        except ModelError as exc:
            report.add(Row(scene_id, f"vertex {index}", "FAIL", str(exc), _vertex_block([legs]), ""))
            continue
        message = verdict.message + crossed_note
        model_body = verdict.vertex or "(no SM UFO vertex)"
        if check_legs != legs:
            model_body = f"UFO legs: [{', '.join(check_legs)}]\n{model_body}"
        report.add(Row(
            scene_id,
            f"vertex {index}",
            "PASS" if verdict.ok else "FAIL",
            message,
            _vertex_block([legs]),
            model_body,
        ))

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m checks.diagrams")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="check a scene file")
    check.add_argument("scene", type=Path)
    check.add_argument("--report", type=Path, help="also write the side-by-side review here")
    check.add_argument("--json", action="store_true", help="print the rows as JSON")
    args = parser.parse_args(argv)
    try:
        report = check_path(args.scene)
    except (SceneError, ModelError, YamlError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    text = format_report(report)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps([row.__dict__ for row in report.rows], indent=2))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
