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
from checks.documents import classify
from checks.language import ok as language_ok
from checks.language import scan as scan_language
from checks.provenance import ProvenanceError, check_inputs_explicit
from checks.renderjob import RenderJob
from checks.traceability import (
    ManifestError,
    check as check_traceability,
    check_documents,
)


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


def seal_render_job(job: RenderJob) -> Seal:
    """Validate and seal one explicit renderer job.

    Unlike the compatibility path below, every input role is supplied by the
    renderer. Parsed narration is traced directly, scene paths are explicit,
    and manifests plus local fit/datacard evidence are included in the seal.
    """
    missing = [str(path) for path in job.seal_paths() if not path.is_file()]
    if missing:
        raise FinalTextError("render job dependency is missing:\n" + "\n".join(missing))
    snap = {str(path): _sha256(path) for path in job.seal_paths()}

    language_paths = [
        item.path for item in job.inputs
        if item.role in {"slide", "narration", "scene"}
    ]
    print("language pass on explicit render inputs")
    language_failures = _language(language_paths)
    _require_same(snap, "during the language pass")
    if language_failures:
        raise FinalTextError(
            "language pass failed; later checks were not run:\n"
            + "\n".join(language_failures)
        )

    print("provenance, number trace, and scene checks on the explicit render job")
    for name, runner in (
        ("provenance", _job_provenance),
        ("traceability", _job_traceability),
        ("diagrams", _job_diagrams),
    ):
        problems = runner(job)
        _require_same(snap, f"during {name}")
        if problems:
            raise FinalTextError(
                f"{name} failed on the explicit render job:\n"
                + "\n".join(problems)
            )
    return Seal(snap)


def _job_provenance(job: RenderJob) -> list[str]:
    failures: list[str] = []
    report = scan_confidentiality(job.root)
    failures.extend(
        f"{item.rule_id} {item.path} {item.note or item.snippet}"
        for item in report.failures
    )
    try:
        rows = check_inputs_explicit(
            job.provenance_inputs(),
            job.root,
            job.manifests,
        )
    except ProvenanceError as exc:
        failures.append(str(exc))
    else:
        failures.extend(f"{rule} {rel} {note}" for rule, rel, note in rows)

    root = job.root.resolve()
    for item in job.inputs:
        path = item.path.resolve()
        try:
            path.relative_to(root)
            continue
        except ValueError:
            pass
        external = scan_confidentiality(path)
        failures.extend(
            f"{finding.rule_id} {finding.path} {finding.note or finding.snippet}"
            for finding in external.failures
            if finding.channel != "provenance"
        )
    return failures


def _job_traceability(job: RenderJob) -> list[str]:
    if not job.trace_documents:
        return []
    manifest = job.primary_manifest
    if manifest is None:
        return [
            f"no sources.yaml in {job.root}; number trace has no primary manifest"
        ]
    try:
        report = check_documents(manifest, job.trace_documents)
    except ManifestError as exc:
        return [str(exc)]
    if report.ok:
        return []
    lines = list(report.source_errors)
    lines.extend(
        f"{item.path}:{item.line} {item.value} {item.surface}"
        for item in report.failures
    )
    lines.extend(
        f"{item.path}:{item.line} {item.message} {item.surface}"
        for item in report.wording
    )
    return lines or ["number trace failed"]


def _job_diagrams(job: RenderJob) -> list[str]:
    if not job.scene_paths:
        return []
    try:
        from checks.diagrams import SceneError, check_path
    except ImportError:
        return ["scene checker is unavailable"]
    problems: list[str] = []
    for scene in job.scene_paths:
        try:
            report = check_path(scene)
        except SceneError as exc:
            problems.append(str(exc))
            continue
        problems.extend(
            f"{row.scene}/{row.item} {row.message}"
            for row in report.rows
            if row.status == "FAIL"
        )
    return problems


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
    report = scan_confidentiality(root)
    failures = [
        f"{item.rule_id} {item.path} {item.note or item.snippet}"
        for item in report.failures
    ]
    root_resolved = root.resolve()
    for path in paths:
        resolved = path.resolve()
        if resolved == root_resolved or root_resolved in resolved.parents:
            continue
        # External render inputs still need the confidentiality marker scan.
        # Their provenance declaration belongs to their own project, so do
        # not turn the lack of a local sources.yaml entry into a duplicate
        # provenance failure here; exact number traceability runs separately.
        external = scan_confidentiality(resolved)
        failures.extend(
            f"{item.rule_id} {item.path} {item.note or item.snippet}"
            for item in external.failures
            if item.channel != "provenance"
        )
    return failures


def _traceability(root: Path, paths: list[Path]) -> list[str]:
    inputs: list[tuple[Path, str]] = []
    for path in paths:
        kind = classify(path)
        if kind is not None:
            inputs.append((path, kind))
    if not inputs:
        # Scene claims/equations are checked by checks.diagrams instead.
        return []
    manifest = _manifest(root)
    if manifest is None:
        return [f"no sources.yaml in {root}; number trace was not given the final text"]
    try:
        report = check_traceability(root, manifest, inputs=inputs)
    except ManifestError as exc:
        return [str(exc)]
    if report.ok:
        return []
    lines = list(report.source_errors)
    for item in report.failures:
        lines.append(f"{item.path}:{item.line} {item.value} {item.surface}")
    lines.extend(
        f"{item.path}:{item.line} {item.message} {item.surface}"
        for item in report.wording
    )
    return lines or ["number trace failed"]


def _diagrams(root: Path, paths: list[Path]) -> list[str]:
    del root
    try:
        from checks.diagrams import SceneError, check_path
    except ImportError:
        return []
    problems: list[str] = []
    for scene in paths:
        if scene.suffix.lower() not in {".yaml", ".yml"}:
            continue
        try:
            raw = scene.read_text(encoding="utf-8")
        except OSError as exc:
            problems.append(str(exc))
            continue
        if not re.search(r"(?m)^\s*scenes\s*:", raw):
            continue
        try:
            report = check_path(scene)
        except SceneError as exc:
            problems.append(str(exc))
            continue
        problems.extend(
            f"{row.scene}/{row.item} {row.message}"
            for row in report.rows
            if row.status == "FAIL"
        )
    return problems


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
