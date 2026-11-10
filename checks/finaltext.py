"""Run checks on the narration and slides that will actually be rendered.

Order, and it is not optional:

1. Language and style (hep-presentation-craft, hep-text-review), which is
   ``checks.language`` for the rules a machine can apply.
2. Only after that passes: provenance, number trace, and, when the module
   is present, the citation and diagram check.

Every one of those reads the files on disk. Rendering must use those same
bytes. If a file changes after the checks, or a caption is not in the
sealed narration, the check fails. A draft that was rewritten for style
is not what gets traced.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from checks.confidentiality import scan as scan_confidentiality
from checks.language import ok as language_ok
from checks.language import scan as scan_language
from checks.traceability import ManifestError, check as check_traceability


class FinalTextError(RuntimeError):
    """The rendered text is not the text the checks read."""


@dataclass(frozen=True)
class Seal:
    """sha256 of each narration and slide file the checks read."""

    hashes: dict[str, str]

    def assert_unchanged(self) -> None:
        for path, digest in self.hashes.items():
            current = _sha256(Path(path))
            if current != digest:
                raise FinalTextError(
                    f"{path} changed after the checks "
                    f"(checked {digest}, render reads {current}). "
                    "Provenance, number trace, and diagram checks apply only "
                    "to the final narration and slides."
                )


def seal_for_render(slide: Path, narration: Path) -> Seal:
    """Language pass, then the other checks, on these two files."""
    slide = Path(slide).resolve()
    narration = Path(narration).resolve()
    if not slide.is_file():
        raise FinalTextError(f"slide file not found: {slide}")
    if not narration.is_file():
        raise FinalTextError(f"narration file not found: {narration}")
    return run_ordered_checks(slide.parent, [slide, narration])


def run_ordered_checks(
    root: Path,
    paths: list[Path],
    *,
    runners: dict | None = None,
) -> Seal:
    """Hash ``paths``, run language, then provenance, trace, and diagrams.

    ``runners`` replaces the real checks in tests. Each later runner is
    called only if the language pass returned no failures, and only if the
    files still have the same hash.
    """
    root = Path(root)
    resolved = [Path(path).resolve() for path in paths]
    snap = {str(path): _sha256(path) for path in resolved}
    language, provenance, trace, diagrams = _bind(runners)
    print("language pass on the final narration and slides")
    language_failures = language(resolved)
    _require_same(snap, "during the language pass")
    if language_failures:
        raise FinalTextError(
            "language pass failed; later checks were not run:\n"
            + "\n".join(language_failures)
        )
    print("provenance, number trace, and diagram checks on those same files")
    for name, runner in (
        ("provenance", provenance),
        ("traceability", trace),
        ("diagrams", diagrams),
    ):
        problems = runner(root, resolved)
        _require_same(snap, f"during {name}")
        if problems:
            raise FinalTextError(
                f"{name} failed on the final narration and slides:\n"
                + "\n".join(problems)
            )
    return Seal(snap)


def assert_captions(narration: Path, captions: list[str], seal: Seal) -> None:
    """Captions must be the sealed narration, not a draft that was rewritten."""
    path = str(Path(narration).resolve())
    if path not in seal.hashes:
        raise FinalTextError(f"{path} was not part of the checked text")
    raw = Path(path).read_bytes()
    if _sha256_bytes(raw) != seal.hashes[path]:
        raise FinalTextError(
            f"{path} changed after the checks and is not what will be captioned"
        )
    text = _collapse(raw.decode("utf-8", errors="replace"))
    for caption in captions:
        if _collapse(caption) not in text:
            raise FinalTextError(
                f"caption is not in the sealed narration: {caption!r}"
            )


def _bind(runners: dict | None):
    runners = runners or {}
    return (
        runners.get("language", _language),
        runners.get("provenance", _provenance),
        runners.get("traceability", _traceability),
        runners.get("diagrams", _diagrams),
    )


def _language(paths: list[Path]) -> list[str]:
    hits = []
    for path in paths:
        hits.extend(scan_language(path))
    if language_ok(hits, strict=False):
        return []
    return [
        f"{hit.path}:{hit.line} {hit.rule_id} {hit.detail}"
        for hit in hits
        if hit.severity == "fail"
    ]


def _provenance(root: Path, paths: list[Path]) -> list[str]:
    del paths
    report = scan_confidentiality(root)
    if report.ok():
        return []
    return [
        f"{item.rule_id} {item.path} {item.note or item.snippet}"
        for item in report.failures
    ]


def _traceability(root: Path, paths: list[Path]) -> list[str]:
    del paths
    manifest = _manifest(root)
    if manifest is None:
        return [f"no sources.yaml in {root}; number trace was not given the final text"]
    try:
        report = check_traceability(root, manifest)
    except ManifestError as exc:
        return [str(exc)]
    if report.ok:
        return []
    lines = list(report.source_errors)
    for item in report.failures:
        lines.append(f"{item.path}:{item.line} {item.value} {item.surface}")
    return lines or ["number trace failed"]


def _diagrams(root: Path, paths: list[Path]) -> list[str]:
    del paths
    scene = root / "scene.yaml"
    if not scene.is_file():
        return []
    try:
        from checks.diagrams import SceneError, check_path
    except ImportError:
        return []
    try:
        report = check_path(scene)
    except SceneError as exc:
        return [str(exc)]
    if report.ok:
        return []
    return [
        f"{row.scene}/{row.item} {row.message}"
        for row in report.rows
        if row.status == "FAIL"
    ]


def _manifest(root: Path) -> Path | None:
    for name in ("sources.yaml", "sources.yml"):
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def _require_same(snap: dict[str, str], when: str) -> None:
    for path, digest in snap.items():
        current = _sha256(Path(path))
        if current != digest:
            raise FinalTextError(
                f"{path} changed {when} "
                f"(checked {digest}, now {current}). "
                "Checks do not run on a pre-rewrite draft."
            )


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
