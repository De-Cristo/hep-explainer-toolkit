"""Hash-bound human review for scientific claim interpretation.

Machine checks can establish source/evidence/value status. Interpretation
approval is a separate human decision. Approvals are bound to the exact
claim, its upstream dependencies, and excerpt bytes; editing any of those
makes the approval stale automatically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from checks.claims import Claim, ClaimRegistry, ClaimRegistryError, load_registry


class ReviewError(ValueError):
    """A review file is malformed or does not match the registry."""


def claim_digest(registry: ClaimRegistry, claim_id: str) -> str:
    cache: dict[str, str] = {}

    def digest(current: str) -> str:
        if current in cache:
            return cache[current]
        claim = registry.get(current)
        local_source_sha256 = None
        if claim.citation.get("local"):
            local_source = (
                registry.path.parent / str(claim.citation["local"])
            ).resolve()
            local_source_sha256 = _sha256(local_source)
        payload = {
            "id": claim.id,
            "kind": claim.kind,
            "statement": claim.statement,
            "origin": claim.origin,
            "citation": claim.citation,
            "excerpt_sha256": _sha256(claim.excerpt),
            "local_source_sha256": local_source_sha256,
            "tex": claim.tex,
            "value": claim.value,
            "unit": claim.unit,
            "context": claim.context,
            "assumptions": claim.assumptions,
            "caveats": claim.caveats,
            "assumption_tags": claim.assumption_tags,
            "depends_on": [
                {"id": dep, "digest": digest(dep)}
                for dep in claim.depends_on
            ],
        }
        body = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
        value = hashlib.sha256(body.encode("utf-8")).hexdigest()
        cache[current] = value
        return value

    return digest(claim_id)


def make_review_file(registry: ClaimRegistry) -> dict[str, object]:
    return {
        "schema_version": 1,
        "registry": registry.path.name,
        "claims": {
            claim_id: {
                "digest": claim_digest(registry, claim_id),
                "decision": "pending",
                "reviewer": "",
                "reviewed_at": "",
                "note": "",
            }
            for claim_id in registry.claims
        },
    }


def load_reviews(path: Path) -> dict[str, object]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewError(f"cannot read review file {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ReviewError(f"{path}: unsupported review schema")
    if not isinstance(data.get("claims"), dict):
        raise ReviewError(f"{path}: claims must be a mapping")
    return data


def review_status(
    registry: ClaimRegistry,
    reviews: dict[str, object],
) -> dict[str, str]:
    raw_claims = reviews.get("claims") or {}
    assert isinstance(raw_claims, dict)
    result: dict[str, str] = {}
    for claim_id, claim in registry.claims.items():
        if claim.review["interpretation"] == "reviewed":
            result[claim_id] = "embedded_reviewed"
            continue
        entry = raw_claims.get(claim_id)
        if not isinstance(entry, dict):
            result[claim_id] = "missing"
            continue
        if str(entry.get("digest") or "") != claim_digest(registry, claim_id):
            result[claim_id] = "stale"
            continue
        decision = str(entry.get("decision") or "pending")
        if decision not in {"pending", "approved", "rejected"}:
            result[claim_id] = "invalid"
        else:
            result[claim_id] = decision
    return result


def strict_ready(registry: ClaimRegistry, reviews: dict[str, object]) -> bool:
    statuses = review_status(registry, reviews)
    for claim_id, claim in registry.claims.items():
        machine_ready = (
            claim.review["source"] == "declared"
            and claim.review["evidence"] == "retrieved"
            and claim.review["value"] != "pending"
        )
        interpretation_ready = statuses[claim_id] in {
            "approved",
            "embedded_reviewed",
        }
        if not machine_ready or not interpretation_ready:
            return False
    return True


def decide(
    registry: ClaimRegistry,
    reviews: dict[str, object],
    claim_id: str,
    reviewer: str,
    note: str,
    decision: str,
) -> None:
    registry.get(claim_id)
    if decision not in {"approved", "rejected"}:
        raise ReviewError("decision must be approved or rejected")
    reviewer = reviewer.strip()
    if not reviewer:
        raise ReviewError("reviewer must be non-empty")
    raw_claims = reviews["claims"]
    assert isinstance(raw_claims, dict)
    entry = raw_claims.setdefault(claim_id, {})
    if not isinstance(entry, dict):
        raise ReviewError(f"review entry for {claim_id} is not a mapping")
    entry.update({
        "digest": claim_digest(registry, claim_id),
        "decision": decision,
        "reviewer": reviewer,
        "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": note.strip(),
    })


def approve(
    registry: ClaimRegistry,
    reviews: dict[str, object],
    claim_id: str,
    reviewer: str,
    note: str,
) -> None:
    decide(registry, reviews, claim_id, reviewer, note, "approved")


def reject(
    registry: ClaimRegistry,
    reviews: dict[str, object],
    claim_id: str,
    reviewer: str,
    note: str,
) -> None:
    decide(registry, reviews, claim_id, reviewer, note, "rejected")


def format_status(registry: ClaimRegistry, reviews: dict[str, object]) -> str:
    statuses = review_status(registry, reviews)
    lines = ["# Human interpretation review", ""]
    raw_claims = reviews.get("claims") or {}
    assert isinstance(raw_claims, dict)
    for claim_id in registry.claims:
        entry = raw_claims.get(claim_id)
        reviewer = ""
        note = ""
        if isinstance(entry, dict):
            reviewer = str(entry.get("reviewer") or "")
            note = str(entry.get("note") or "")
        lines.append(f"- {claim_id}: **{statuses[claim_id]}**")
        if reviewer:
            lines.append(f"  reviewer: {reviewer}")
        if note:
            lines.append(f"  note: {note}")
    lines.extend(["", f"Strict release ready: **{'yes' if strict_ready(registry, reviews) else 'no'}**"])
    return "\n".join(lines) + "\n"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_reviews(path: Path, data: dict[str, object]) -> None:
    """Atomically persist a review file."""
    _write_json(path, data)


def _write_json(path: Path, data: dict[str, object]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    fd, raw_tmp = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m checks.review")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create a pending hash-bound review file")
    init.add_argument("registry", type=Path)
    init.add_argument("out", type=Path)

    check = sub.add_parser("check", help="check approvals against current claim/evidence bytes")
    check.add_argument("registry", type=Path)
    check.add_argument("reviews", type=Path)
    check.add_argument("--strict", action="store_true")

    approve_cmd = sub.add_parser("approve", help="record one explicit human approval")
    approve_cmd.add_argument("registry", type=Path)
    approve_cmd.add_argument("reviews", type=Path)
    approve_cmd.add_argument("claim_id")
    approve_cmd.add_argument("--reviewer", required=True)
    approve_cmd.add_argument("--note", default="")

    reject_cmd = sub.add_parser("reject", help="record one explicit human rejection")
    reject_cmd.add_argument("registry", type=Path)
    reject_cmd.add_argument("reviews", type=Path)
    reject_cmd.add_argument("claim_id")
    reject_cmd.add_argument("--reviewer", required=True)
    reject_cmd.add_argument("--note", default="")

    args = parser.parse_args(argv)
    try:
        registry = load_registry(args.registry)
        if args.command == "init":
            _write_json(args.out, make_review_file(registry))
            print(f"wrote pending review file: {args.out}")
            return 0
        reviews = load_reviews(args.reviews)
        if args.command == "approve":
            approve(registry, reviews, args.claim_id, args.reviewer, args.note)
            _write_json(args.reviews, reviews)
            print(f"approved {args.claim_id} as {args.reviewer}")
            return 0
        if args.command == "reject":
            reject(registry, reviews, args.claim_id, args.reviewer, args.note)
            _write_json(args.reviews, reviews)
            print(f"rejected {args.claim_id} as {args.reviewer}")
            return 0
        text = format_status(registry, reviews)
        print(text, end="")
        if args.strict and not strict_ready(registry, reviews):
            return 1
        return 0
    except (ClaimRegistryError, ReviewError, OSError) as exc:
        print(f"review: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
