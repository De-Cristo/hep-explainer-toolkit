"""Citation and excerpt checks for a scene file.

A citation id on its own is not a pass. The excerpt has to live in the
repository, name the same arXiv id or DOI and the same locator, and:

- for an equation, contain that equation
- for a diagram, list the same vertices the diagram draws

Prose claims still need that stored excerpt. The report prints the claim
beside the quote so a person can see whether the quote actually supports
the sentence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from checks.ufo_model import canonical_token
from checks.yamlsubset import YamlError, load as load_yaml

_NEW_ARXIV = re.compile(r"^\d{4}\.\d{4,5}$")
_OLD_ARXIV = re.compile(r"^[a-z][a-z0-9-]*(?:\.[a-z]{2})?/\d{7}$", re.IGNORECASE)
_DOI = re.compile(r"^10\.\d{4,}/\S+$", re.IGNORECASE)
_MIN_QUOTE = 40


class SceneError(ValueError):
    """The scene file or an excerpt is not usable."""


@dataclass
class Row:
    scene: str
    item: str
    status: str
    message: str
    item_body: str
    excerpt_body: str


@dataclass
class CitationReport:
    rows: list[Row] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(row.status == "PASS" for row in self.rows)

    def add(self, row: Row) -> None:
        self.rows.append(row)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_document(path: Path) -> dict:
    try:
        data = load_yaml(path.read_text(encoding="utf-8"))
    except (OSError, YamlError) as exc:
        raise SceneError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SceneError(f"{path} must be a mapping")
    return data


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_tex(text: str) -> str:
    """Drop presentation differences that do not change an equation."""
    value = text.strip()
    if value.startswith("$$") and value.endswith("$$"):
        value = value[2:-2]
    value = value.replace("$", "")
    value = value.replace(r"\dagger", "DAG").replace(r"\dag", "DAG")
    value = re.sub(r"\\(?:text|mathrm|rm|operatorname)\b", "", value)
    value = re.sub(r"\\(?:left|right|quad|qquad)\b", "", value)
    for spacing in (r"\,", r"\;", r"\!", r"\:", r"\ "):
        value = value.replace(spacing, "")
    value = value.replace("~", "")
    value = re.sub(r"\s+", "", value)
    previous = None
    while previous != value:
        previous = value
        value = re.sub(r"\^\{([^{}]+)\}", r"^\1", value)
        value = re.sub(r"_\{([^{}]+)\}", r"_\1", value)
    value = value.replace("{", "").replace("}", "")
    return value


def normalize_arxiv(value: str) -> str:
    text = value.strip()
    text = re.sub(r"(?i)^arxiv:\s*", "", text)
    text = re.sub(r"v\d+$", "", text)
    return text


def valid_arxiv(value: str) -> bool:
    text = normalize_arxiv(value)
    return bool(_NEW_ARXIV.fullmatch(text) or _OLD_ARXIV.fullmatch(text))


def valid_doi(value: str) -> bool:
    text = re.sub(r"(?i)^doi:\s*", "", value.strip())
    return bool(_DOI.fullmatch(text))


def normalize_doi(value: str) -> str:
    return re.sub(r"(?i)^doi:\s*", "", value.strip()).lower()


def locator_ok(value: str) -> bool:
    text = normalize_space(value)
    return bool(text) and any(char.isdigit() for char in text)


def vertex_key(legs: list[str]) -> tuple[str, ...]:
    return tuple(sorted(canonical_token(str(leg)) for leg in legs))


def diagram_key(vertices: list[list[str]]) -> tuple[tuple[str, ...], ...]:
    return tuple(sorted(vertex_key(legs) for legs in vertices))


def resolve_inside(repo: Path, base: Path, raw: str) -> Path:
    """Resolve a scene-relative path.

    The file has to stay inside the repository, or, when the scene itself
    is outside the repository (a scratch file), inside that scene's folder.
    """
    path = Path(str(raw))
    if path.is_absolute():
        raise SceneError(f"path must be relative to the scene: {raw}")
    resolved = (base / path).resolve()
    root = repo.resolve()
    base_resolved = base.resolve()
    in_repo = resolved == root or root in resolved.parents
    in_scene = resolved == base_resolved or base_resolved in resolved.parents
    if not in_repo and not in_scene:
        raise SceneError(f"path leaves the scene and the repository: {raw}")
    return resolved


def format_report(report: CitationReport) -> str:
    lines = ["# Scene check", ""]
    if not report.rows:
        lines.append("No claims.")
        return "\n".join(lines)
    for row in report.rows:
        lines.append(f"## {row.scene} / {row.item}  {row.status}")
        lines.append(row.message)
        lines.append("--- item ---")
        lines.append(row.item_body.rstrip() or "(empty)")
        lines.append("--- cited excerpt ---")
        lines.append(row.excerpt_body.rstrip() or "(none)")
        lines.append("")
    failed = sum(1 for row in report.rows if row.status == "FAIL")
    lines.append(f"{failed} failure(s), {len(report.rows) - failed} passed")
    return "\n".join(lines)
