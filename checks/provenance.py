"""Allowlist of input files and where each one came from.

Images, plot data, slide HTML, and narration files are refused unless
``sources.yaml`` names a public source. ``toy`` is accepted only when a
generator under ``examples/toy/`` regenerates the file and the sha256
matches. A manifest entry that only says ``toy`` is refused.

The same ``sources.yaml`` holds the number-trace ``sources:`` list.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from checks.documents import classify
from checks.yamlsubset import YamlError, load as load_yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
_TOY_ROOT = REPO_ROOT / "examples" / "toy"
_ARXIV = re.compile(r"^\d{4}\.\d{4,5}$")
_PAS = re.compile(r"(?i)^CMS[\s-]*PAS[\s-]*[A-Z0-9]+-\d{2}-\d{3,4}$")
_SKIP_NAMES = {
    "sources.yaml",
    "sources.yml",
    "confidentiality-allow.yaml",
    "readme.md",
    "inventory.md",
}
_IMAGE = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf"}
_PLOT = {".json", ".csv"}
# npm metadata is not a physics plot. A fit-result JSON still is.
_NOT_PLOT = {"package.json", "package-lock.json"}
_NARRATION_SUFFIX = {".txt", ".md", ".markdown", ".srt", ".vtt", ".yaml", ".yml"}
_NARRATION_NAME = re.compile(
    r"(narrat|voiceover|voice-over|voice_over|spoken|\btts\b|transcript|(?<![A-Za-z])script(?![A-Za-z]))",
    re.IGNORECASE,
)


class ProvenanceError(ValueError):
    """The provenance section of a manifest cannot be read."""


@dataclass
class FileDeclaration:
    path: Path
    source_type: str
    detail: str
    generator: str | None = None
    sha256: str | None = None


def input_role(path: Path) -> str | None:
    """Return why ``path`` is a pipeline input, or None."""
    if path.name.startswith(".") or path.name.lower() in _SKIP_NAMES:
        return None
    suffix = path.suffix.lower()
    if suffix in _IMAGE:
        return "image"
    if path.name.lower() in _NOT_PLOT:
        return None
    if suffix in _PLOT or (suffix in {".txt", ".dat"} and "datacard" in path.stem.lower()):
        return "plot"
    if suffix in {".html", ".htm"}:
        return "slide"
    if suffix in _NARRATION_SUFFIX and _NARRATION_NAME.search(path.stem):
        return "narration"
    if classify(path) == "narration":
        return "narration"
    return None


def load_declarations(manifest: Path) -> list[FileDeclaration]:
    try:
        data = load_yaml(manifest.read_text(encoding="utf-8"))
    except (OSError, YamlError) as exc:
        raise ProvenanceError(f"cannot read {manifest}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProvenanceError(f"{manifest} must be a mapping")
    entries = data.get("files") or []
    if not isinstance(entries, list):
        raise ProvenanceError(f"{manifest} files: must be a list")
    declarations: list[FileDeclaration] = []
    base = manifest.parent
    for entry in entries:
        declarations.append(_declaration(entry, base, manifest))
    return declarations


def discover_manifests(root: Path, skip_prefixes: list[str]) -> list[Path]:
    found: list[Path] = []
    if root.is_file():
        return found
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).resolve().relative_to(root.resolve()).as_posix()
        if rel_dir == ".":
            rel_dir = ""
        dirnames[:] = [
            name
            for name in dirnames
            if not name.startswith(".")
            and not _skipped(f"{rel_dir}/{name}".lstrip("/"), skip_prefixes)
        ]
        if rel_dir and _skipped(rel_dir, skip_prefixes):
            continue
        for name in sorted(filenames):
            if name in {"sources.yaml", "sources.yml"}:
                found.append(Path(dirpath) / name)
    return found


def check_inputs(
    files: list[Path],
    root: Path,
    manifests: list[Path],
) -> list[tuple[str, str, str]]:
    """Return ``(rule_id, relative_path, note)`` failures.

    ``files`` is the set under consideration (already skip-filtered).
    """
    declarations: list[FileDeclaration] = []
    for manifest in manifests:
        declarations.extend(load_declarations(manifest))
    by_path = {item.path.resolve(): item for item in declarations}
    failures: list[tuple[str, str, str]] = []
    seen: set[Path] = set()
    root_resolved = root.resolve()
    for path in files:
        role = input_role(path)
        if role is None:
            continue
        resolved = path.resolve()
        seen.add(resolved)
        declaration = by_path.get(resolved)
        rel = _relative(path, root_resolved)
        if declaration is None:
            failures.append(
                (
                    "undeclared",
                    rel,
                    f"{role} file has no public source in sources.yaml",
                )
            )
            continue
        failures.extend(_verify(declaration, rel))
    for declaration in declarations:
        resolved = declaration.path.resolve()
        if resolved in seen or not _is_relative_to(resolved, root_resolved):
            continue
        if not resolved.exists():
            failures.append(
                (
                    "missing_file",
                    _relative(declaration.path, root_resolved),
                    "provenance entry points at a file that is not in the folder",
                )
            )
    return failures


def check_inputs_explicit(
    inputs: list[tuple[Path, str]],
    root: Path,
    manifests: list[Path] | tuple[Path, ...],
) -> list[tuple[str, str, str]]:
    """Check explicitly typed render inputs without filename inference."""
    declarations: list[FileDeclaration] = []
    for manifest in manifests:
        declarations.extend(load_declarations(Path(manifest)))
    by_path = {item.path.resolve(): item for item in declarations}
    failures: list[tuple[str, str, str]] = []
    root_resolved = Path(root).resolve()
    for path, role in inputs:
        resolved = Path(path).resolve()
        rel = _relative(resolved, root_resolved)
        declaration = by_path.get(resolved)
        if declaration is None:
            failures.append(
                (
                    "undeclared",
                    rel,
                    f"{role} file has no public source in sources.yaml",
                )
            )
            continue
        failures.extend(_verify(declaration, rel))
    return failures


def _declaration(entry: object, base: Path, manifest: Path) -> FileDeclaration:
    if not isinstance(entry, dict) or "path" not in entry or "source" not in entry:
        raise ProvenanceError(f"{manifest.name} file entry needs path and source")
    raw = Path(str(entry["path"]))
    if raw.is_absolute() or ".." in raw.parts:
        raise ProvenanceError(f"{manifest.name} path must stay inside the deck: {raw}")
    path = (base / raw).resolve()
    source = entry["source"]
    if isinstance(source, str):
        if source.lower() != "toy":
            raise ProvenanceError(
                f"{manifest.name} source string {source!r} is not a public source; "
                "use hepdata, arxiv, cds, or toy with a generator"
            )
        return FileDeclaration(path, "toy", "toy")
    if not isinstance(source, dict) or "type" not in source:
        raise ProvenanceError(f"{manifest.name} source for {raw} needs a type")
    source_type = str(source["type"]).lower()
    if source_type == "toy":
        generator = source.get("generator")
        digest = source.get("sha256")
        return FileDeclaration(
            path,
            "toy",
            "toy",
            None if generator in (None, "") else str(generator),
            None if digest in (None, "") else str(digest).lower(),
        )
    if source_type == "hepdata":
        record = str(source.get("record") or "").strip()
        lowered = record.lower()
        if record == "" or not (
            lowered.startswith(("http://", "https://"))
            or "hepdata" in lowered
            or record.isdigit()
        ):
            raise ProvenanceError(f"{raw} hepdata record is missing or not an id/URL")
        return FileDeclaration(path, "hepdata", record)
    if source_type == "arxiv":
        arxiv = str(source.get("arxiv") or source.get("id") or "").strip()
        if not _ARXIV.fullmatch(arxiv):
            raise ProvenanceError(f"{raw} arxiv id {arxiv!r} is not NNNN.NNNNN")
        return FileDeclaration(path, "arxiv", arxiv)
    if source_type == "cds":
        link = str(source.get("url") or source.get("link") or source.get("cds") or "").strip()
        if not _valid_cds(link):
            raise ProvenanceError(
                f"{raw} cds source needs a https://cds.cern.ch/... link or a CMS-PAS id"
            )
        return FileDeclaration(path, "cds", link)
    raise ProvenanceError(
        f"{raw} source type {source_type!r} is not hepdata, arxiv, cds, or toy"
    )


def _valid_cds(link: str) -> bool:
    lowered = link.lower()
    if lowered.startswith(("http://", "https://")) and "cds.cern.ch" in lowered:
        return True
    return _PAS.fullmatch(link) is not None


def _verify(declaration: FileDeclaration, rel: str) -> list[tuple[str, str, str]]:
    if declaration.source_type != "toy":
        return []
    if not declaration.generator or not declaration.sha256:
        return [
            (
                "toy_provenance",
                rel,
                "toy is not a source by itself; name a generator under examples/toy/ and a sha256",
            )
        ]
    script = _generator_path(declaration.generator)
    if script is None:
        return [
            (
                "toy_provenance",
                rel,
                f"generator {declaration.generator} must be a file under examples/toy/",
            )
        ]
    if not declaration.path.is_file():
        return [("missing_file", rel, "declared toy file is missing")]
    on_disk = _sha256(declaration.path)
    if on_disk != declaration.sha256:
        return [
            (
                "toy_provenance",
                rel,
                f"file sha256 {on_disk} does not match manifest {declaration.sha256}",
            )
        ]
    produced, error = _rerun(script, declaration.path.name)
    if error is not None:
        return [("toy_provenance", rel, error)]
    if produced != declaration.sha256:
        return [
            (
                "toy_provenance",
                rel,
                f"rerun of {script.name} produced {produced}, manifest says {declaration.sha256}",
            )
        ]
    return []


def _generator_path(raw: str) -> Path | None:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        return None
    script = (REPO_ROOT / path).resolve()
    if not _is_relative_to(script, _TOY_ROOT.resolve()) or not script.is_file():
        return None
    return script


def _rerun(script: Path, output_name: str) -> tuple[str | None, str | None]:
    """Return ``(sha256, None)`` or ``(None, error)``."""
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / output_name
        try:
            completed = subprocess.run(
                [sys.executable, str(script), str(dest)],
                cwd=REPO_ROOT,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, f"could not rerun {script.name}: {exc}"
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            return None, f"{script.name} exited {completed.returncode}: {detail}"
        if not dest.is_file():
            return None, f"{script.name} did not write {output_name}"
        return _sha256(dest), None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _skipped(rel: str, prefixes: list[str]) -> bool:
    rel = rel.replace("\\", "/")
    for prefix in prefixes:
        prefix = prefix.replace("\\", "/").strip("/")
        if rel == prefix or rel.startswith(prefix + "/"):
            return True
    return False


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.name


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
