"""Staged authoring workflow: source -> candidates -> reviewed handoff.

This module deliberately separates candidate science from the canonical claim
registry. An agent may draft candidates, but only an explicit promote command
can add one candidate to claims.yaml, and promotion always leaves
interpretation review pending.

The handoff command goes the other direction: it exports a machine-readable
authoring plan only when every scientific claim used by the storyboard has a
current human approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from checks.brief import BriefError, load_brief
from checks.citations import (
    locator_ok,
    normalize_space,
    normalize_tex,
    valid_arxiv,
    valid_doi,
)
from checks.claims import ClaimRegistryError, load_registry
from checks.review import (
    ReviewError,
    claim_digest,
    load_reviews,
    review_status,
)
from checks.storyboard import StoryboardError, check_storyboard, narration_segments
from checks.yamldump import dumps as dump_yaml
from checks.yamlsubset import YamlError, load as load_yaml

_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_KINDS = {"claim", "number", "equation", "diagram", "definition"}
_ORIGINS = {"theory", "measurement", "derived", "illustrative", "definition"}


class AuthoringError(ValueError):
    """The authoring pack or promotion request is unsafe or malformed."""


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    proposed_claim_id: str
    kind: str
    origin: str
    statement: str
    locator: str
    quote: str
    context: dict[str, object]
    assumptions: tuple[str, ...]
    caveats: tuple[str, ...]
    depends_on: tuple[str, ...]
    assumption_tags: tuple[str, ...]
    tex: str | None
    value: object | None
    unit: str | None
    vertices: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class AuthoringPack:
    path: Path
    visibility: str
    brief: Path | None
    source: Path
    source_sha256: str
    citation: dict[str, object]
    candidates: tuple[Candidate, ...]

    def get(self, candidate_id: str) -> Candidate:
        for candidate in self.candidates:
            if candidate.candidate_id == candidate_id:
                return candidate
        raise AuthoringError(
            f"{self.path}: unknown candidate {candidate_id!r}"
        )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def init_pack(
    source: Path,
    out: Path,
    *,
    visibility: str,
    brief: Path | None = None,
    arxiv: str | None = None,
    doi: str | None = None,
) -> Path:
    source = Path(source).resolve()
    out = Path(out).resolve()
    if not source.is_file():
        raise AuthoringError(f"source not found: {source}")
    _read_source_text(source)
    if visibility not in {"public", "private"}:
        raise AuthoringError("visibility must be public or private")

    citation: dict[str, object] = {}
    if visibility == "private":
        if arxiv or doi:
            raise AuthoringError(
                "private source packs use local evidence; do not pass arxiv/doi"
            )
        citation["local"] = _relative(out.parent, source)
    else:
        if arxiv:
            if not valid_arxiv(arxiv):
                raise AuthoringError(f"invalid arxiv id {arxiv!r}")
            citation["arxiv"] = arxiv
        if doi:
            if not valid_doi(doi):
                raise AuthoringError(f"invalid doi {doi!r}")
            citation["doi"] = doi
        if not citation:
            raise AuthoringError(
                "public source packs require --arxiv and/or --doi"
            )

    brief_value = None
    if brief is not None:
        brief = Path(brief).resolve()
        try:
            load_brief(brief)
        except BriefError as exc:
            raise AuthoringError(str(exc)) from exc
        brief_value = _relative(out.parent, brief)

    data: dict[str, object] = {
        "schema_version": 1,
        "visibility": visibility,
    }
    if brief_value is not None:
        data["brief"] = brief_value
    data["source"] = {
        "path": _relative(out.parent, source),
        "sha256": sha256(source),
        "citation": citation,
    }
    data["candidates"] = []
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise AuthoringError(f"refusing to overwrite existing pack: {out}")
    out.write_text(dump_yaml(data), encoding="utf-8")
    return out


def load_pack(path: Path) -> AuthoringPack:
    path = Path(path).resolve()
    try:
        data = load_yaml(path.read_text(encoding="utf-8"))
    except (OSError, YamlError) as exc:
        raise AuthoringError(f"cannot read authoring pack {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise AuthoringError(f"{path}: unsupported authoring schema")

    visibility = str(data.get("visibility") or "").strip()
    if visibility not in {"public", "private"}:
        raise AuthoringError(f"{path}: visibility must be public or private")

    raw_source = data.get("source")
    if not isinstance(raw_source, dict):
        raise AuthoringError(f"{path}: source must be a mapping")
    source_raw = str(raw_source.get("path") or "").strip()
    if not source_raw:
        raise AuthoringError(f"{path}: source.path is required")
    source = _resolve_relative(path.parent, source_raw)
    if not source.is_file():
        raise AuthoringError(f"{path}: source file not found: {source_raw}")
    _read_source_text(source)
    expected_sha = str(raw_source.get("sha256") or "").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise AuthoringError(f"{path}: source.sha256 must be a lowercase sha256")
    actual_sha = sha256(source)
    if actual_sha != expected_sha:
        raise AuthoringError(
            f"{path}: source changed since the pack was created "
            f"({expected_sha[:12]} != {actual_sha[:12]})"
        )

    citation = raw_source.get("citation")
    if not isinstance(citation, dict):
        raise AuthoringError(f"{path}: source.citation must be a mapping")
    _validate_source_citation(path, visibility, citation, source)

    brief_path = None
    if data.get("brief"):
        brief_path = _resolve_relative(path.parent, str(data["brief"]))
        try:
            load_brief(brief_path)
        except BriefError as exc:
            raise AuthoringError(str(exc)) from exc

    raw_candidates = data.get("candidates")
    if not isinstance(raw_candidates, list):
        raise AuthoringError(f"{path}: candidates must be a list")
    candidates: list[Candidate] = []
    seen_candidate: set[str] = set()
    seen_claim: set[str] = set()
    source_text = normalize_space(_read_source_text(source))
    for index, raw in enumerate(raw_candidates, 1):
        candidate = _candidate(path, raw, index, source_text)
        if candidate.candidate_id in seen_candidate:
            raise AuthoringError(
                f"{path}: duplicate candidate id {candidate.candidate_id}"
            )
        if candidate.proposed_claim_id in seen_claim:
            raise AuthoringError(
                f"{path}: duplicate proposed claim id {candidate.proposed_claim_id}"
            )
        seen_candidate.add(candidate.candidate_id)
        seen_claim.add(candidate.proposed_claim_id)
        candidates.append(candidate)

    return AuthoringPack(
        path=path,
        visibility=visibility,
        brief=brief_path,
        source=source,
        source_sha256=expected_sha,
        citation=dict(citation),
        candidates=tuple(candidates),
    )


def index_source(source: Path) -> dict[str, object]:
    source = Path(source).resolve()
    text = _read_source_text(source)
    lines = text.splitlines()
    landmarks: list[dict[str, object]] = []
    tex = re.compile(
        r"^\s*\\(?P<level>section|subsection|subsubsection)\*?\{(?P<title>.+?)\}"
    )
    md = re.compile(r"^\s*(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$")
    for number, line in enumerate(lines, 1):
        match = tex.match(line)
        if match:
            landmarks.append({
                "line": number,
                "level": match.group("level"),
                "title": normalize_space(match.group("title")),
            })
            continue
        match = md.match(line)
        if match:
            landmarks.append({
                "line": number,
                "level": f"h{len(match.group('marks'))}",
                "title": normalize_space(match.group("title")),
            })
    return {
        "schema_version": 1,
        "source": str(source),
        "sha256": sha256(source),
        "line_count": len(lines),
        "landmarks": landmarks,
    }


def promote_candidate(
    pack_path: Path,
    candidate_id: str,
    *,
    registry_path: Path,
    excerpt_dir: Path,
) -> tuple[Path, Path]:
    pack = load_pack(pack_path)
    candidate = pack.get(candidate_id)
    registry_path = Path(registry_path).resolve()
    excerpt_dir = Path(excerpt_dir)
    if not excerpt_dir.is_absolute():
        excerpt_dir = (registry_path.parent / excerpt_dir).resolve()
    excerpt_dir.mkdir(parents=True, exist_ok=True)

    if registry_path.exists():
        try:
            raw_registry = load_yaml(registry_path.read_text(encoding="utf-8"))
        except (OSError, YamlError) as exc:
            raise AuthoringError(
                f"cannot read registry {registry_path}: {exc}"
            ) from exc
        if not isinstance(raw_registry, dict):
            raise AuthoringError(f"{registry_path}: registry must be a mapping")
        registry_visibility = str(
            raw_registry.get("visibility") or "public"
        ).strip()
        if registry_visibility != pack.visibility:
            raise AuthoringError(
                f"{registry_path}: visibility {registry_visibility!r} "
                f"does not match pack visibility {pack.visibility!r}"
            )
        raw_claims = raw_registry.get("claims")
        if not isinstance(raw_claims, list):
            raise AuthoringError(f"{registry_path}: claims must be a list")
        existing_ids = {
            str(item.get("id"))
            for item in raw_claims
            if isinstance(item, dict) and item.get("id")
        }
    else:
        raw_registry = {
            "visibility": pack.visibility,
            "claims": [],
        }
        raw_claims = raw_registry["claims"]
        assert isinstance(raw_claims, list)
        existing_ids = set()

    if candidate.proposed_claim_id in existing_ids:
        raise AuthoringError(
            f"{registry_path}: claim {candidate.proposed_claim_id} already exists"
        )
    missing_dependencies = [
        dep for dep in candidate.depends_on if dep not in existing_ids
    ]
    if missing_dependencies:
        raise AuthoringError(
            "promote dependencies first: " + ", ".join(missing_dependencies)
        )

    excerpt_name = _excerpt_name(candidate.proposed_claim_id)
    excerpt_path = excerpt_dir / excerpt_name
    if excerpt_path.exists():
        raise AuthoringError(
            f"refusing to overwrite existing excerpt: {excerpt_path}"
        )

    citation = _claim_citation(pack, candidate, registry_path.parent)
    excerpt = _excerpt_mapping(pack, candidate, excerpt_path.parent)
    claim = _claim_mapping(
        candidate,
        citation,
        _relative(registry_path.parent, excerpt_path),
    )
    raw_claims.append(claim)

    old_registry = (
        registry_path.read_text(encoding="utf-8")
        if registry_path.exists()
        else None
    )
    try:
        excerpt_path.write_text(dump_yaml(excerpt), encoding="utf-8")
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(dump_yaml(raw_registry), encoding="utf-8")
        load_registry(registry_path)
    except Exception:
        if excerpt_path.exists():
            excerpt_path.unlink()
        if old_registry is None:
            if registry_path.exists():
                registry_path.unlink()
        else:
            registry_path.write_text(old_registry, encoding="utf-8")
        raise

    return registry_path, excerpt_path


def make_handoff(
    scene_path: Path,
    reviews_path: Path,
    out: Path,
) -> dict[str, object]:
    scene_path = Path(scene_path).resolve()
    reviews_path = Path(reviews_path).resolve()
    out = Path(out).resolve()
    try:
        scene_doc = load_yaml(scene_path.read_text(encoding="utf-8"))
    except (OSError, YamlError) as exc:
        raise AuthoringError(f"cannot read scene {scene_path}: {exc}") from exc
    if not isinstance(scene_doc, dict):
        raise AuthoringError(f"{scene_path}: scene must be a mapping")

    try:
        storyboard = check_storyboard(scene_path)
    except StoryboardError as exc:
        raise AuthoringError(str(exc)) from exc
    if not storyboard.ok:
        raise AuthoringError(
            "storyboard is not ready: " + "; ".join(storyboard.problems)
        )

    registry_raw = str(scene_doc.get("claim_registry") or "").strip()
    if not registry_raw:
        raise AuthoringError(f"{scene_path}: claim_registry is required")
    registry_path = _resolve_relative(scene_path.parent, registry_raw)
    try:
        registry = load_registry(registry_path)
        reviews = load_reviews(reviews_path)
    except (ClaimRegistryError, ReviewError) as exc:
        raise AuthoringError(str(exc)) from exc

    statuses = review_status(registry, reviews)
    used = _used_claims(scene_doc)
    blocked = [
        claim_id
        for claim_id in used
        if statuses.get(claim_id) not in {"approved", "embedded_reviewed"}
    ]
    if blocked:
        details = ", ".join(
            f"{claim_id}={statuses.get(claim_id, 'missing')}"
            for claim_id in blocked
        )
        raise AuthoringError(
            "approved authoring handoff refused; human review incomplete: "
            + details
        )

    brief = None
    if scene_doc.get("brief"):
        brief_path = _resolve_relative(
            scene_path.parent,
            str(scene_doc["brief"]),
        )
        try:
            parsed = load_brief(brief_path)
        except BriefError as exc:
            raise AuthoringError(str(exc)) from exc
        brief = {
            "topic": parsed.topic,
            "audience_profile": parsed.audience_profile,
            "knows": list(parsed.knows),
            "introduce": list(parsed.introduce),
            "purpose": parsed.purpose,
            "medium": parsed.medium,
            "learning_goal": parsed.learning_goal,
            "duration_minutes": parsed.duration_minutes,
            "required_distinctions": list(parsed.required_distinctions),
            "avoid": list(parsed.avoid),
            "sha256": sha256(brief_path),
        }

    scenes: list[dict[str, object]] = []
    for raw_scene in scene_doc.get("scenes") or []:
        if not isinstance(raw_scene, dict):
            continue
        segments = narration_segments(raw_scene)
        claims = []
        for raw_claim in raw_scene.get("claims") or []:
            if not isinstance(raw_claim, dict):
                continue
            ref = str(raw_claim.get("claim_ref") or "").strip()
            if not ref:
                continue
            claims.append({
                "claim_ref": ref,
                "audience_wording": str(
                    raw_claim.get("text")
                    or raw_claim.get("tex")
                    or ""
                ).strip(),
            })
        scenes.append({
            "id": str(raw_scene.get("id") or ""),
            "question": str(raw_scene.get("question") or ""),
            "takeaway": str(raw_scene.get("takeaway") or ""),
            "requires": list(raw_scene.get("requires") or []),
            "introduces": list(raw_scene.get("introduces") or []),
            "covers_distinctions": list(
                raw_scene.get("covers_distinctions") or []
            ),
            "visual_purpose": str(raw_scene.get("visual_purpose") or ""),
            "why_next": str(raw_scene.get("why_next") or ""),
            "narration": [
                {"cue": segment.cue, "text": segment.text}
                for segment in segments
            ],
            "claims": claims,
            "method_validation": raw_scene.get("method_validation"),
        })

    claim_payload = []
    for claim_id in used:
        claim = registry.get(claim_id)
        claim_payload.append({
            "id": claim.id,
            "digest": claim_digest(registry, claim.id),
            "status": statuses[claim.id],
            "kind": claim.kind,
            "origin": claim.origin,
            "canonical_statement": claim.statement,
            "context": claim.context,
            "effective_assumptions": list(
                registry.effective_assumptions(claim.id)
            ),
            "caveats": list(claim.caveats),
            "depends_on": list(claim.depends_on),
        })

    comparisons = []
    used_set = set(used)
    for item in registry.comparisons:
        refs = {
            item.left,
            item.right,
            *item.same_when,
            *item.differs_when,
        }
        if not refs.intersection(used_set):
            continue
        comparisons.append({
            "id": item.id,
            "left": item.left,
            "right": item.right,
            "same_when": list(item.same_when),
            "differs_when": list(item.differs_when),
        })

    payload = {
        "schema_version": 1,
        "kind": "approved_authoring_handoff",
        "scene": str(scene_path),
        "scene_sha256": sha256(scene_path),
        "registry": str(registry.path),
        "registry_visibility": registry.visibility,
        "reviews": str(reviews_path),
        "reviews_sha256": sha256(reviews_path),
        "brief": brief,
        "claims": claim_payload,
        "comparisons": comparisons,
        "scenes": scenes,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def _candidate(
    path: Path,
    raw: object,
    index: int,
    source_text: str,
) -> Candidate:
    if not isinstance(raw, dict):
        raise AuthoringError(f"{path}: candidate {index} must be a mapping")
    candidate_id = str(raw.get("id") or "").strip()
    proposed = str(raw.get("proposed_claim_id") or "").strip()
    if not _ID.fullmatch(candidate_id):
        raise AuthoringError(
            f"{path}: candidate {index} has invalid id {candidate_id!r}"
        )
    if not _ID.fullmatch(proposed):
        raise AuthoringError(
            f"{path}/{candidate_id}: invalid proposed_claim_id {proposed!r}"
        )
    kind = str(raw.get("kind") or "").strip()
    origin = str(raw.get("origin") or "").strip()
    if kind not in _KINDS:
        raise AuthoringError(
            f"{path}/{candidate_id}: kind must be one of {sorted(_KINDS)}"
        )
    if origin not in _ORIGINS:
        raise AuthoringError(
            f"{path}/{candidate_id}: origin must be one of {sorted(_ORIGINS)}"
        )
    statement = normalize_space(str(raw.get("statement") or ""))
    locator = normalize_space(str(raw.get("locator") or ""))
    quote = normalize_space(str(raw.get("quote") or ""))
    if not statement:
        raise AuthoringError(f"{path}/{candidate_id}: statement is required")
    if not locator_ok(locator):
        raise AuthoringError(
            f"{path}/{candidate_id}: locator needs a numbered location"
        )
    if len(quote) < 40:
        raise AuthoringError(
            f"{path}/{candidate_id}: quote must be at least 40 characters"
        )
    if quote not in source_text:
        raise AuthoringError(
            f"{path}/{candidate_id}: quote does not occur in the source"
        )

    context = raw.get("context") or {}
    if not isinstance(context, dict):
        raise AuthoringError(f"{path}/{candidate_id}: context must be a mapping")
    assumptions = _strings(raw.get("assumptions"), path, candidate_id, "assumptions")
    caveats = _strings(raw.get("caveats"), path, candidate_id, "caveats")
    depends_on = _strings(raw.get("depends_on"), path, candidate_id, "depends_on")
    assumption_tags = _strings(
        raw.get("assumption_tags"),
        path,
        candidate_id,
        "assumption_tags",
    )

    tex = None
    if kind == "equation":
        tex = str(raw.get("tex") or "").strip()
        if not tex:
            raise AuthoringError(f"{path}/{candidate_id}: equation needs tex")
        if normalize_tex(tex) not in normalize_tex(quote):
            raise AuthoringError(
                f"{path}/{candidate_id}: equation tex is absent from the quote"
            )

    value = raw.get("value")
    unit = None if raw.get("unit") in (None, "") else str(raw.get("unit"))
    if kind == "number" and value is None:
        raise AuthoringError(f"{path}/{candidate_id}: number needs value")

    raw_vertices = raw.get("vertices") or []
    vertices: list[tuple[str, ...]] = []
    if raw_vertices:
        if not isinstance(raw_vertices, list):
            raise AuthoringError(
                f"{path}/{candidate_id}: vertices must be a list"
            )
        for vertex in raw_vertices:
            if not isinstance(vertex, list) or not vertex:
                raise AuthoringError(
                    f"{path}/{candidate_id}: every vertex must be a non-empty list"
                )
            vertices.append(tuple(str(item) for item in vertex))
    if kind == "diagram" and not vertices:
        raise AuthoringError(
            f"{path}/{candidate_id}: diagram candidate needs vertices"
        )

    return Candidate(
        candidate_id=candidate_id,
        proposed_claim_id=proposed,
        kind=kind,
        origin=origin,
        statement=statement,
        locator=locator,
        quote=quote,
        context=dict(context),
        assumptions=assumptions,
        caveats=caveats,
        depends_on=depends_on,
        assumption_tags=assumption_tags,
        tex=tex,
        value=value,
        unit=unit,
        vertices=tuple(vertices),
    )


def _validate_source_citation(
    path: Path,
    visibility: str,
    citation: dict,
    source: Path,
) -> None:
    arxiv = str(citation.get("arxiv") or "").strip()
    doi = str(citation.get("doi") or "").strip()
    local = str(citation.get("local") or "").strip()
    if visibility == "private":
        if arxiv or doi or not local:
            raise AuthoringError(
                f"{path}: private pack source.citation must contain only local"
            )
        if _resolve_relative(path.parent, local) != source:
            raise AuthoringError(
                f"{path}: private source.citation.local must point to source.path"
            )
        return
    if local:
        raise AuthoringError(
            f"{path}: public pack source.citation cannot use local"
        )
    if not arxiv and not doi:
        raise AuthoringError(
            f"{path}: public source needs arxiv and/or doi"
        )
    if arxiv and not valid_arxiv(arxiv):
        raise AuthoringError(f"{path}: invalid arxiv id {arxiv!r}")
    if doi and not valid_doi(doi):
        raise AuthoringError(f"{path}: invalid doi {doi!r}")


def _claim_citation(
    pack: AuthoringPack,
    candidate: Candidate,
    registry_parent: Path,
) -> dict[str, object]:
    citation: dict[str, object] = {}
    if pack.visibility == "private":
        citation["local"] = _relative(registry_parent, pack.source)
    else:
        if pack.citation.get("arxiv"):
            citation["arxiv"] = pack.citation["arxiv"]
        if pack.citation.get("doi"):
            citation["doi"] = pack.citation["doi"]
    citation["locator"] = candidate.locator
    return citation


def _excerpt_mapping(
    pack: AuthoringPack,
    candidate: Candidate,
    excerpt_parent: Path,
) -> dict[str, object]:
    excerpt: dict[str, object] = {}
    if pack.visibility == "private":
        excerpt["local"] = _relative(excerpt_parent, pack.source)
    else:
        if pack.citation.get("arxiv"):
            excerpt["arxiv"] = pack.citation["arxiv"]
        if pack.citation.get("doi"):
            excerpt["doi"] = pack.citation["doi"]
    excerpt["locator"] = candidate.locator
    excerpt["quote"] = candidate.quote
    if candidate.vertices:
        excerpt["vertices"] = [list(item) for item in candidate.vertices]
    return excerpt


def _claim_mapping(
    candidate: Candidate,
    citation: dict[str, object],
    excerpt_relative: str,
) -> dict[str, object]:
    claim: dict[str, object] = {
        "id": candidate.proposed_claim_id,
        "kind": candidate.kind,
        "origin": candidate.origin,
        "statement": candidate.statement,
        "citation": citation,
        "excerpt": excerpt_relative,
    }
    if candidate.tex is not None:
        claim["tex"] = candidate.tex
    if candidate.value is not None:
        claim["value"] = candidate.value
    if candidate.unit is not None:
        claim["unit"] = candidate.unit
    if candidate.context:
        claim["context"] = candidate.context
    if candidate.assumptions:
        claim["assumptions"] = list(candidate.assumptions)
    if candidate.caveats:
        claim["caveats"] = list(candidate.caveats)
    if candidate.depends_on:
        claim["depends_on"] = list(candidate.depends_on)
    if candidate.assumption_tags:
        claim["assumption_tags"] = list(candidate.assumption_tags)
    claim["review"] = {
        "source": "declared",
        "evidence": "retrieved",
        "value": "matched" if candidate.kind == "number" else "not_applicable",
        "interpretation": "pending",
    }
    return claim


def _used_claims(scene_doc: dict) -> list[str]:
    found: list[str] = []
    for scene in scene_doc.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        for item in scene.get("claims") or []:
            if not isinstance(item, dict):
                continue
            ref = str(item.get("claim_ref") or "").strip()
            if ref and ref not in found:
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


def _excerpt_name(claim_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", claim_id).strip("-")
    return safe + ".yaml"


def _strings(
    raw: object,
    path: Path,
    candidate_id: str,
    field: str,
) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise AuthoringError(
            f"{path}/{candidate_id}: {field} must be a list"
        )
    values = tuple(normalize_space(str(item)) for item in raw)
    if any(not value for value in values):
        raise AuthoringError(
            f"{path}/{candidate_id}: {field} contains an empty item"
        )
    return values


def _resolve_relative(base: Path, raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        raise AuthoringError(f"path must be relative: {raw}")
    return (base / path).resolve()


def _relative(base: Path, path: Path) -> str:
    return Path(os.path.relpath(path.resolve(), base.resolve())).as_posix()


def _read_source_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise AuthoringError(
            f"{path}: authoring source must be UTF-8 text; extract PDFs first"
        ) from exc
    except OSError as exc:
        raise AuthoringError(f"cannot read source {path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m checks.authoring")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create a candidate-authoring pack")
    init.add_argument("source", type=Path)
    init.add_argument("--out", type=Path, required=True)
    init.add_argument(
        "--visibility",
        choices=("public", "private"),
        required=True,
    )
    init.add_argument("--brief", type=Path)
    init.add_argument("--arxiv")
    init.add_argument("--doi")

    index = sub.add_parser("index", help="index headings in a text source")
    index.add_argument("source", type=Path)
    index.add_argument("--out", type=Path, required=True)

    check = sub.add_parser("check", help="validate candidates against source bytes")
    check.add_argument("pack", type=Path)

    promote = sub.add_parser(
        "promote",
        help="explicitly promote one candidate into a claim registry",
    )
    promote.add_argument("pack", type=Path)
    promote.add_argument("candidate_id")
    promote.add_argument("--registry", type=Path, required=True)
    promote.add_argument("--excerpt-dir", type=Path, default=Path("excerpts"))

    handoff = sub.add_parser(
        "handoff",
        help="export an authoring plan only from human-approved claims",
    )
    handoff.add_argument("scene", type=Path)
    handoff.add_argument("--reviews", type=Path, required=True)
    handoff.add_argument("--out", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            path = init_pack(
                args.source,
                args.out,
                visibility=args.visibility,
                brief=args.brief,
                arxiv=args.arxiv,
                doi=args.doi,
            )
            print(f"authoring pack: {path}")
            return 0
        if args.command == "index":
            payload = index_source(args.source)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(
                json.dumps(payload, indent=2) + "\n",
                encoding="utf-8",
            )
            print(
                f"source index: {len(payload['landmarks'])} landmark(s); "
                f"{args.out}"
            )
            return 0
        if args.command == "check":
            pack = load_pack(args.pack)
            print(
                f"authoring candidates: PASS; {len(pack.candidates)} candidate(s); "
                f"source {pack.source_sha256[:12]}"
            )
            return 0
        if args.command == "promote":
            registry, excerpt = promote_candidate(
                args.pack,
                args.candidate_id,
                registry_path=args.registry,
                excerpt_dir=args.excerpt_dir,
            )
            print(
                f"promoted {args.candidate_id}; registry={registry}; "
                f"excerpt={excerpt}; interpretation=pending"
            )
            return 0
        payload = make_handoff(args.scene, args.reviews, args.out)
        print(
            f"approved authoring handoff: {len(payload['claims'])} claim(s), "
            f"{len(payload['scenes'])} scene(s); {args.out}"
        )
        return 0
    except (
        AuthoringError,
        ClaimRegistryError,
        ReviewError,
        StoryboardError,
        OSError,
        YamlError,
    ) as exc:
        print(f"authoring: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
