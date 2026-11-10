"""Project-local registry of reusable scientific claims.

A claim stores stable scientific content and its evidence. Audience-specific
scenes may phrase that content differently but reference the same claim id.
Review status is deliberately multi-dimensional: a declared source is not
the same thing as retrieved evidence, a matched value, or a human-reviewed
interpretation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from checks.citations import (
    locator_ok,
    normalize_arxiv,
    normalize_doi,
    normalize_space,
    normalize_tex,
    valid_arxiv,
    valid_doi,
)
from checks.yamlsubset import YamlError, load as load_yaml

_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_KINDS = {"claim", "number", "equation", "diagram", "definition"}
_ORIGINS = {"theory", "measurement", "derived", "illustrative", "definition"}
_REVIEW = {
    "source": {"declared", "pending"},
    "evidence": {"retrieved", "pending"},
    "value": {"matched", "not_applicable", "pending"},
    "interpretation": {"reviewed", "pending"},
}


class ClaimRegistryError(ValueError):
    """A claim registry is malformed or internally inconsistent."""


@dataclass(frozen=True)
class Comparison:
    id: str
    left: str
    right: str
    same_when: tuple[str, ...]
    differs_when: tuple[str, ...]


@dataclass(frozen=True)
class Claim:
    id: str
    kind: str
    statement: str
    origin: str
    citation: dict[str, object]
    excerpt: Path
    tex: str | None
    value: object | None
    unit: str | None
    context: dict[str, object]
    assumptions: tuple[str, ...]
    caveats: tuple[str, ...]
    depends_on: tuple[str, ...]
    assumption_tags: tuple[str, ...]
    review: dict[str, str]

    @property
    def strict_ready(self) -> bool:
        return (
            self.review["source"] == "declared"
            and self.review["evidence"] == "retrieved"
            and self.review["value"] != "pending"
            and self.review["interpretation"] == "reviewed"
        )


@dataclass(frozen=True)
class ClaimRegistry:
    path: Path
    claims: dict[str, Claim]
    comparisons: tuple[Comparison, ...] = ()
    visibility: str = "public"

    def effective_assumptions(self, claim_id: str) -> tuple[str, ...]:
        """Return explicit and upstream assumptions without duplication."""
        seen_claims: set[str] = set()
        values: list[str] = []

        def visit(current: str) -> None:
            if current in seen_claims:
                return
            seen_claims.add(current)
            claim = self.get(current)
            for dep in claim.depends_on:
                visit(dep)
            for value in (*claim.assumption_tags, *claim.assumptions):
                if value not in values:
                    values.append(value)

        visit(claim_id)
        return tuple(values)

    def get(self, claim_id: str) -> Claim:
        try:
            return self.claims[claim_id]
        except KeyError as exc:
            raise ClaimRegistryError(
                f"{self.path}: unknown claim_ref {claim_id!r}"
            ) from exc

    @property
    def strict_ready(self) -> bool:
        return all(claim.strict_ready for claim in self.claims.values())


def load_registry(path: Path) -> ClaimRegistry:
    path = Path(path).resolve()
    try:
        data = load_yaml(path.read_text(encoding="utf-8"))
    except (OSError, YamlError) as exc:
        raise ClaimRegistryError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ClaimRegistryError(f"{path} must be a mapping")
    visibility = str(data.get("visibility") or "public").strip()
    if visibility not in {"public", "private"}:
        raise ClaimRegistryError(
            f"{path}: visibility must be public or private"
        )
    raw_claims = data.get("claims")
    if not isinstance(raw_claims, list) or not raw_claims:
        raise ClaimRegistryError(f"{path}: claims must be a non-empty list")

    claims: dict[str, Claim] = {}
    for index, raw in enumerate(raw_claims, 1):
        claim = _claim(path, raw, index, visibility)
        if claim.id in claims:
            raise ClaimRegistryError(f"{path}: duplicate claim id {claim.id}")
        claims[claim.id] = claim

    raw_comparisons = data.get("comparisons") or []
    if not isinstance(raw_comparisons, list):
        raise ClaimRegistryError(f"{path}: comparisons must be a list")
    comparisons = tuple(
        _comparison(path, raw, index, claims)
        for index, raw in enumerate(raw_comparisons, 1)
    )
    _validate_dependencies(path, claims)
    return ClaimRegistry(path, claims, comparisons, visibility)


def registry_dependencies(path: Path) -> tuple[Path, ...]:
    registry = load_registry(path)
    found = [registry.path, *(claim.excerpt for claim in registry.claims.values())]
    for claim in registry.claims.values():
        raw = claim.citation.get("local")
        if raw:
            source = (registry.path.parent / str(raw)).resolve()
            if source not in found:
                found.append(source)
    return tuple(found)


def format_review(registry: ClaimRegistry) -> str:
    lines = [
        "# Scientific claim review",
        "",
        f"Registry: {registry.path}",
        f"Visibility: **{registry.visibility}**",
        "",
    ]
    for claim in registry.claims.values():
        lines.extend([
            f"## {claim.id}",
            "",
            f"- Kind: **{claim.kind}**",
            f"- Origin: **{claim.origin}**",
            f"- Canonical statement: {claim.statement}",
            f"- Citation: {_citation_text(claim.citation)}",
            f"- Excerpt: {claim.excerpt}",
            f"- Source: **{claim.review['source']}**",
            f"- Evidence: **{claim.review['evidence']}**",
            f"- Value: **{claim.review['value']}**",
            f"- Interpretation: **{claim.review['interpretation']}**",
        ])
        if claim.value is not None:
            suffix = f" {claim.unit}" if claim.unit else ""
            lines.append(f"- Registered value: **{claim.value}{suffix}**")
        if claim.context:
            rendered = ", ".join(f"{key}={value}" for key, value in claim.context.items())
            lines.append(f"- Context: {rendered}")
        if claim.assumptions:
            lines.append("- Assumptions: " + "; ".join(claim.assumptions))
        if claim.depends_on:
            lines.append("- Depends on: " + ", ".join(claim.depends_on))
        if claim.assumption_tags:
            lines.append("- Assumption tags: " + ", ".join(claim.assumption_tags))
        effective = registry.effective_assumptions(claim.id)
        if effective:
            lines.append("- Effective assumptions: " + "; ".join(effective))
        if claim.caveats:
            lines.append("- Caveats: " + "; ".join(claim.caveats))
        lines.extend([
            "",
            f"Strict release ready: **{'yes' if claim.strict_ready else 'no'}**",
            "",
        ])
    if registry.comparisons:
        lines.extend(["# Definition comparisons", ""])
        for comparison in registry.comparisons:
            lines.extend([
                f"## {comparison.id}",
                "",
                f"- Left: {comparison.left}",
                f"- Right: {comparison.right}",
                "- Same when supported by: " + ", ".join(comparison.same_when),
                "- Differ when supported by: " + ", ".join(comparison.differs_when),
                "",
            ])
    return "\n".join(lines).rstrip() + "\n"


def report_to_json(registry: ClaimRegistry) -> dict[str, object]:
    return {
        "registry": str(registry.path),
        "visibility": registry.visibility,
        "strict_ready": registry.strict_ready,
        "claims": [
            {
                "id": claim.id,
                "kind": claim.kind,
                "statement": claim.statement,
                "origin": claim.origin,
                "citation": claim.citation,
                "excerpt": str(claim.excerpt),
                "tex": claim.tex,
                "value": None if claim.value is None else str(claim.value),
                "unit": claim.unit,
                "context": claim.context,
                "assumptions": list(claim.assumptions),
                "caveats": list(claim.caveats),
                "depends_on": list(claim.depends_on),
                "assumption_tags": list(claim.assumption_tags),
                "effective_assumptions": list(registry.effective_assumptions(claim.id)),
                "review": claim.review,
                "strict_ready": claim.strict_ready,
            }
            for claim in registry.claims.values()
        ],
        "comparisons": [
            {
                "id": item.id,
                "left": item.left,
                "right": item.right,
                "same_when": list(item.same_when),
                "differs_when": list(item.differs_when),
            }
            for item in registry.comparisons
        ],
    }


def _claim(
    registry_path: Path,
    raw: object,
    index: int,
    visibility: str,
) -> Claim:
    if not isinstance(raw, dict):
        raise ClaimRegistryError(f"{registry_path}: claim {index} must be a mapping")
    claim_id = str(raw.get("id") or "").strip()
    if not _ID.fullmatch(claim_id):
        raise ClaimRegistryError(
            f"{registry_path}: claim {index} id {claim_id!r} must match {_ID.pattern}"
        )
    kind = str(raw.get("kind") or "").strip()
    if kind not in _KINDS:
        raise ClaimRegistryError(
            f"{registry_path}/{claim_id}: kind must be one of {sorted(_KINDS)}"
        )
    statement = normalize_space(str(raw.get("statement") or ""))
    if not statement:
        raise ClaimRegistryError(f"{registry_path}/{claim_id}: statement is required")
    origin = str(raw.get("origin") or "").strip()
    if origin not in _ORIGINS:
        raise ClaimRegistryError(
            f"{registry_path}/{claim_id}: origin must be one of {sorted(_ORIGINS)}"
        )

    citation = raw.get("citation")
    if not isinstance(citation, dict):
        raise ClaimRegistryError(f"{registry_path}/{claim_id}: citation is required")
    _validate_citation(registry_path, claim_id, citation, visibility)

    excerpt_raw = str(raw.get("excerpt") or "").strip()
    if not excerpt_raw:
        raise ClaimRegistryError(f"{registry_path}/{claim_id}: excerpt is required")
    excerpt = (registry_path.parent / excerpt_raw).resolve()
    if not excerpt.is_file():
        raise ClaimRegistryError(
            f"{registry_path}/{claim_id}: excerpt file not found: {excerpt_raw}"
        )
    _validate_excerpt(registry_path, claim_id, citation, excerpt, kind, raw)

    tex = None
    if kind == "equation":
        tex = str(raw.get("tex") or "").strip()
        if not tex:
            raise ClaimRegistryError(f"{registry_path}/{claim_id}: equation needs tex")

    value = raw.get("value")
    unit = None if raw.get("unit") in (None, "") else str(raw.get("unit"))
    if kind == "number" and value is None:
        raise ClaimRegistryError(f"{registry_path}/{claim_id}: number claim needs value")

    context = raw.get("context") or {}
    if not isinstance(context, dict):
        raise ClaimRegistryError(f"{registry_path}/{claim_id}: context must be a mapping")
    assumptions = _strings(raw.get("assumptions"), registry_path, claim_id, "assumptions")
    caveats = _strings(raw.get("caveats"), registry_path, claim_id, "caveats")
    depends_on = _strings(raw.get("depends_on"), registry_path, claim_id, "depends_on")
    assumption_tags = _strings(
        raw.get("assumption_tags"), registry_path, claim_id, "assumption_tags"
    )
    review = _review(raw.get("review"), registry_path, claim_id)
    if kind == "number" and review["value"] == "not_applicable":
        raise ClaimRegistryError(
            f"{registry_path}/{claim_id}: a number claim cannot mark value not_applicable"
        )

    return Claim(
        id=claim_id,
        kind=kind,
        statement=statement,
        origin=origin,
        citation=dict(citation),
        excerpt=excerpt,
        tex=tex,
        value=value,
        unit=unit,
        context=dict(context),
        assumptions=assumptions,
        caveats=caveats,
        depends_on=depends_on,
        assumption_tags=assumption_tags,
        review=review,
    )


def _comparison(
    path: Path,
    raw: object,
    index: int,
    claims: dict[str, Claim],
) -> Comparison:
    if not isinstance(raw, dict):
        raise ClaimRegistryError(f"{path}: comparison {index} must be a mapping")
    comparison_id = str(raw.get("id") or "").strip()
    if not _ID.fullmatch(comparison_id):
        raise ClaimRegistryError(
            f"{path}: comparison {index} has invalid id {comparison_id!r}"
        )
    left = str(raw.get("left") or "").strip()
    right = str(raw.get("right") or "").strip()
    if left not in claims or right not in claims:
        raise ClaimRegistryError(
            f"{path}/{comparison_id}: left and right must reference registered claims"
        )
    same_when = _strings(raw.get("same_when"), path, comparison_id, "same_when")
    differs_when = _strings(raw.get("differs_when"), path, comparison_id, "differs_when")
    unknown = [
        ref for ref in (*same_when, *differs_when)
        if ref not in claims
    ]
    if unknown:
        raise ClaimRegistryError(
            f"{path}/{comparison_id}: unknown comparison support claim(s): "
            + ", ".join(unknown)
        )
    if not same_when or not differs_when:
        raise ClaimRegistryError(
            f"{path}/{comparison_id}: comparisons need same_when and differs_when support"
        )
    return Comparison(comparison_id, left, right, same_when, differs_when)


def _validate_dependencies(path: Path, claims: dict[str, Claim]) -> None:
    for claim in claims.values():
        unknown = [item for item in claim.depends_on if item not in claims]
        if unknown:
            raise ClaimRegistryError(
                f"{path}/{claim.id}: unknown depends_on claim(s): "
                + ", ".join(unknown)
            )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(claim_id: str) -> None:
        if claim_id in visited:
            return
        if claim_id in visiting:
            raise ClaimRegistryError(
                f"{path}: dependency cycle contains {claim_id}"
            )
        visiting.add(claim_id)
        for dep in claims[claim_id].depends_on:
            visit(dep)
        visiting.remove(claim_id)
        visited.add(claim_id)

    for claim_id in claims:
        visit(claim_id)


def _validate_citation(
    path: Path,
    claim_id: str,
    citation: dict,
    visibility: str,
) -> None:
    arxiv = str(citation.get("arxiv") or "")
    doi = str(citation.get("doi") or "")
    local = str(citation.get("local") or "").strip()
    if local and (arxiv or doi):
        raise ClaimRegistryError(
            f"{path}/{claim_id}: local evidence cannot be mixed with arxiv/doi"
        )
    if local:
        if visibility != "private":
            raise ClaimRegistryError(
                f"{path}/{claim_id}: local evidence is allowed only in visibility: private registries"
            )
        source = (path.parent / local).resolve()
        if not source.is_file():
            raise ClaimRegistryError(
                f"{path}/{claim_id}: local evidence file not found: {local}"
            )
    elif not arxiv and not doi:
        raise ClaimRegistryError(
            f"{path}/{claim_id}: citation needs arxiv, doi, or private local evidence"
        )
    if arxiv and not valid_arxiv(arxiv):
        raise ClaimRegistryError(f"{path}/{claim_id}: invalid arxiv id {arxiv!r}")
    if doi and not valid_doi(doi):
        raise ClaimRegistryError(f"{path}/{claim_id}: invalid doi {doi!r}")
    if not locator_ok(str(citation.get("locator") or "")):
        raise ClaimRegistryError(f"{path}/{claim_id}: citation needs a numbered locator")


def _validate_excerpt(
    registry_path: Path,
    claim_id: str,
    citation: dict,
    excerpt_path: Path,
    kind: str,
    raw: dict,
) -> None:
    try:
        excerpt = load_yaml(excerpt_path.read_text(encoding="utf-8"))
    except (OSError, YamlError) as exc:
        raise ClaimRegistryError(
            f"{registry_path}/{claim_id}: cannot read excerpt {excerpt_path}: {exc}"
        ) from exc
    if not isinstance(excerpt, dict):
        raise ClaimRegistryError(f"{registry_path}/{claim_id}: excerpt must be a mapping")
    if citation.get("arxiv"):
        if normalize_arxiv(str(citation["arxiv"])) != normalize_arxiv(
            str(excerpt.get("arxiv") or "")
        ):
            raise ClaimRegistryError(f"{registry_path}/{claim_id}: excerpt arxiv mismatch")
    if citation.get("doi") or excerpt.get("doi"):
        if normalize_doi(str(citation.get("doi") or "")) != normalize_doi(
            str(excerpt.get("doi") or "")
        ):
            raise ClaimRegistryError(f"{registry_path}/{claim_id}: excerpt doi mismatch")
    if citation.get("local"):
        cited_source = (registry_path.parent / str(citation["local"])).resolve()
        excerpt_local = str(excerpt.get("local") or "").strip()
        if not excerpt_local:
            raise ClaimRegistryError(
                f"{registry_path}/{claim_id}: private excerpt needs local source path"
            )
        excerpt_source = (excerpt_path.parent / excerpt_local).resolve()
        if cited_source != excerpt_source:
            raise ClaimRegistryError(
                f"{registry_path}/{claim_id}: excerpt local source mismatch"
            )
    if normalize_space(str(citation.get("locator") or "")) != normalize_space(
        str(excerpt.get("locator") or "")
    ):
        raise ClaimRegistryError(f"{registry_path}/{claim_id}: excerpt locator mismatch")
    quote = normalize_space(str(excerpt.get("quote") or ""))
    if len(quote) < 40:
        raise ClaimRegistryError(
            f"{registry_path}/{claim_id}: excerpt quote is missing or too short"
        )
    if citation.get("local"):
        source_path = (registry_path.parent / str(citation["local"])).resolve()
        try:
            source_text = normalize_space(source_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ClaimRegistryError(
                f"{registry_path}/{claim_id}: cannot read local evidence {source_path}: {exc}"
            ) from exc
        if quote not in source_text:
            raise ClaimRegistryError(
                f"{registry_path}/{claim_id}: excerpt quote is not present in local evidence"
            )
    if kind == "equation":
        tex = str(raw.get("tex") or "")
        if normalize_tex(tex) not in normalize_tex(quote):
            raise ClaimRegistryError(
                f"{registry_path}/{claim_id}: equation does not appear in excerpt"
            )
    if kind == "diagram" and not excerpt.get("vertices"):
        raise ClaimRegistryError(
            f"{registry_path}/{claim_id}: diagram evidence needs excerpt vertices"
        )


def _review(raw: object, path: Path, claim_id: str) -> dict[str, str]:
    mapping = raw or {}
    if not isinstance(mapping, dict):
        raise ClaimRegistryError(f"{path}/{claim_id}: review must be a mapping")
    result: dict[str, str] = {}
    defaults = {
        "source": "pending",
        "evidence": "pending",
        "value": "pending",
        "interpretation": "pending",
    }
    for key, allowed in _REVIEW.items():
        value = str(mapping.get(key) or defaults[key])
        if value not in allowed:
            raise ClaimRegistryError(
                f"{path}/{claim_id}: review.{key} must be one of {sorted(allowed)}"
            )
        result[key] = value
    return result


def _strings(raw: object, path: Path, claim_id: str, field: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ClaimRegistryError(f"{path}/{claim_id}: {field} must be a list")
    values = tuple(normalize_space(str(item)) for item in raw)
    if any(not value for value in values):
        raise ClaimRegistryError(f"{path}/{claim_id}: {field} contains an empty item")
    return values


def _citation_text(citation: dict[str, object]) -> str:
    parts = []
    if citation.get("arxiv"):
        parts.append(f"arXiv:{citation['arxiv']}")
    if citation.get("doi"):
        parts.append(f"doi:{citation['doi']}")
    if citation.get("local"):
        parts.append(f"local:{citation['local']}")
    parts.append(str(citation.get("locator") or ""))
    return ", ".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m checks.claims")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="validate a scientific claim registry")
    check.add_argument("registry", type=Path)
    check.add_argument("--report", type=Path)
    check.add_argument("--json", action="store_true")
    check.add_argument(
        "--strict",
        action="store_true",
        help="also fail while any review dimension remains pending",
    )
    args = parser.parse_args(argv)
    try:
        registry = load_registry(args.registry)
    except ClaimRegistryError as exc:
        print(f"claim registry: FAIL: {exc}", file=sys.stderr)
        return 1

    review = format_review(registry)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(review, encoding="utf-8")
    if args.json:
        print(json.dumps(report_to_json(registry), indent=2))
    else:
        print(review, end="")
    if args.strict and not registry.strict_ready:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
