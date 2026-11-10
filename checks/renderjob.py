"""Explicit contract between authoring checks and the renderer.

Renderers must declare the files they read and the role of each file. The
validation layer must not infer those roles from filenames. The same job
also records the parsed narration documents used for number traceability,
the scene files that need citation/diagram checks, and the manifests and
local evidence files whose bytes must stay fixed after validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from checks.documents import Document, document_from_lines
from checks.yamlsubset import YamlError, load as load_yaml

_SOURCE_REQUIRED = {"slide", "narration", "asset", "figure", "plot"}


@dataclass(frozen=True)
class RenderInput:
    path: Path
    role: str

    def resolved(self) -> "RenderInput":
        return RenderInput(Path(self.path).resolve(), self.role)


@dataclass(frozen=True)
class RenderJob:
    root: Path
    inputs: tuple[RenderInput, ...]
    manifests: tuple[Path, ...]
    trace_documents: tuple[Document, ...] = ()
    scene_paths: tuple[Path, ...] = ()
    dependencies: tuple[Path, ...] = ()

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(item.path for item in self.inputs)

    @property
    def primary_manifest(self) -> Path | None:
        root = self.root.resolve()
        for manifest in self.manifests:
            if manifest.parent.resolve() == root:
                return manifest
        return None

    def provenance_inputs(self) -> list[tuple[Path, str]]:
        """Inputs whose public origin must be declared explicitly."""
        root = self.root.resolve()
        selected: list[tuple[Path, str]] = []
        for item in self.inputs:
            path = item.path.resolve()
            external = not _inside(path, root)
            if item.role in _SOURCE_REQUIRED or external:
                selected.append((path, item.role))
        return selected

    def seal_paths(self) -> tuple[Path, ...]:
        ordered = [
            *(item.path.resolve() for item in self.inputs),
            *(path.resolve() for path in self.manifests),
            *(path.resolve() for path in self.dependencies),
        ]
        unique: list[Path] = []
        seen: set[Path] = set()
        for path in ordered:
            if path not in seen:
                seen.add(path)
                unique.append(path)
        return tuple(unique)


def find_project_root(start: Path) -> Path:
    """Return the nearest ancestor carrying sources.yaml, else the directory."""
    current = Path(start).resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        if any((directory / name).is_file() for name in ("sources.yaml", "sources.yml")):
            return directory
    return current


def scene_render_job(scene: Path, document: dict) -> RenderJob:
    """Build the exact validation/render contract for a scene explanation."""
    from checks.claims import registry_dependencies
    from checks.storyboard import narration_segments

    scene = Path(scene).resolve()
    inputs = [RenderInput(scene, "scene")]
    brief_raw = document.get("brief")
    if brief_raw:
        inputs.append(
            RenderInput((scene.parent / str(brief_raw)).resolve(), "brief")
        )
    registry_raw = document.get("claim_registry")
    if registry_raw:
        registry_path = (scene.parent / str(registry_raw)).resolve()
        for dependency in registry_dependencies(registry_path):
            inputs.append(RenderInput(dependency, "evidence"))

    texts: list[str] = []
    for item in document.get("scenes") or []:
        for segment in narration_segments(item):
            texts.append(segment.text)
        visual = item.get("visual") or {}
        raw_diagram = visual.get("diagram")
        if raw_diagram:
            inputs.append(
                RenderInput((scene.parent / str(raw_diagram)).resolve(), "diagram")
            )
        raw_file = visual.get("file")
        if raw_file:
            inputs.append(
                RenderInput((scene.parent / str(raw_file)).resolve(), "asset")
            )
        for claim in item.get("claims") or []:
            if not isinstance(claim, dict):
                continue
            raw_excerpt = claim.get("excerpt")
            if raw_excerpt:
                inputs.append(
                    RenderInput(
                        (scene.parent / str(raw_excerpt)).resolve(),
                        "evidence",
                    )
                )

    unique: list[RenderInput] = []
    seen: set[Path] = set()
    for item in inputs:
        path = item.path.resolve()
        if path not in seen:
            seen.add(path)
            unique.append(RenderInput(path, item.role))

    return make_render_job(
        find_project_root(scene.parent),
        unique,
        trace_documents=[
            document_from_lines(scene, "narration", texts)
        ],
        scene_paths=[scene],
    )


def make_render_job(
    root: Path,
    inputs: list[RenderInput],
    *,
    trace_documents: list[Document] | tuple[Document, ...] = (),
    scene_paths: list[Path] | tuple[Path, ...] = (),
) -> RenderJob:
    root = Path(root).resolve()
    resolved = tuple(item.resolved() for item in inputs)
    manifests = _manifests(root, resolved)
    dependencies = _manifest_dependencies(manifests)
    return RenderJob(
        root=root,
        inputs=resolved,
        manifests=manifests,
        trace_documents=tuple(trace_documents),
        scene_paths=tuple(Path(path).resolve() for path in scene_paths),
        dependencies=dependencies,
    )


def _manifests(root: Path, inputs: tuple[RenderInput, ...]) -> tuple[Path, ...]:
    directories = [root, *(item.path.parent for item in inputs)]
    found: list[Path] = []
    seen: set[Path] = set()
    for directory in directories:
        directory = directory.resolve()
        for name in ("sources.yaml", "sources.yml"):
            candidate = directory / name
            if candidate.is_file():
                candidate = candidate.resolve()
                if candidate not in seen:
                    seen.add(candidate)
                    found.append(candidate)
                break
    return tuple(found)


def _manifest_dependencies(manifests: tuple[Path, ...]) -> tuple[Path, ...]:
    """Local evidence read by provenance/number checks is part of the seal."""
    found: list[Path] = []
    seen: set[Path] = set()
    for manifest in manifests:
        try:
            data = load_yaml(manifest.read_text(encoding="utf-8"))
        except (OSError, YamlError):
            continue
        if not isinstance(data, dict):
            continue
        for entry in data.get("sources") or []:
            if not isinstance(entry, dict):
                continue
            source = entry.get("source")
            if not isinstance(source, dict):
                continue
            if str(source.get("type") or "") not in {"fit_json", "datacard"}:
                continue
            raw = source.get("path")
            if not raw:
                continue
            path = (manifest.parent / str(raw)).resolve()
            if path not in seen:
                seen.add(path)
                found.append(path)
    return tuple(found)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
