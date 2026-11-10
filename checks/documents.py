"""Turn a deck file into slide text and narration text.

Traceability reads what a viewer sees and what would be sent to TTS.
Style, scripts, and layout numbers stay out of that text. HTML comments
are kept for the confidentiality scan, which reads the file bytes
directly, and omitted here so a reviewer note is not treated as a claim.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from checks.pdftext import extract_pdf_text

_NARRATION_NAME = re.compile(
    r"(narrat|voiceover|voice-over|voice_over|spoken|\btts\b|transcript|(?<![A-Za-z])script(?![A-Za-z]))",
    re.IGNORECASE,
)
_SKIP_NAMES = {
    "sources.yaml",
    "sources.yml",
    "confidentiality-allow.yaml",
    "readme.md",
    "inventory.md",
}
_BLOCK = {
    "p",
    "div",
    "li",
    "tr",
    "br",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "section",
    "table",
    "ul",
    "ol",
    "figure",
    "figcaption",
    "header",
    "footer",
    "blockquote",
}
_PAGE_MARK = re.compile(r"^\s*(?:slide\s+)?\d+\s*/\s*\d+\s*$", re.IGNORECASE)
_FENCE = re.compile(r"^\s*```")


@dataclass(frozen=True)
class Region:
    start: int
    end: int
    line: int
    hints: frozenset[str] = field(default_factory=frozenset)


@dataclass
class Document:
    path: str
    kind: str  # "slide" or "narration"
    text: str
    regions: list[Region]


def discover(root: Path) -> list[tuple[Path, str]]:
    """Find slide and narration files under ``root``."""
    found: list[tuple[Path, str]] = []
    if root.is_file():
        kind = classify(root)
        if kind:
            found.append((root, kind))
        return found
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if not name.startswith(".") and name not in {"node_modules", "__pycache__", "upstream", "media"}
        ]
        for name in sorted(filenames):
            path = Path(dirpath) / name
            kind = classify(path)
            if kind:
                found.append((path, kind))
    return found


def classify(path: Path) -> str | None:
    """Return ``slide``, ``narration``, or ``None`` for files that are not claims."""
    if path.name.startswith("."):
        return None
    if path.name.lower() in _SKIP_NAMES:
        return None
    suffix = path.suffix.lower()
    if _NARRATION_NAME.search(path.stem):
        if suffix in {".txt", ".md", ".markdown", ".srt", ".vtt", ".html", ".htm"}:
            return "narration"
    if suffix in {".html", ".htm", ".pdf", ".md", ".markdown"}:
        return "slide"
    return None


def load_document(path: Path, kind: str) -> list[Document]:
    """Read ``path`` into one or two documents (a deck can embed narration)."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    label = path.as_posix()
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = extract_pdf_text(path.read_bytes())
        return [_plain(label, kind, text, hints_for_lines=True)]
    if suffix in {".html", ".htm"}:
        return _from_html(label, raw, kind)
    if suffix in {".md", ".markdown"}:
        return [_markdown(label, kind, raw)]
    return [_plain(label, kind, raw, hints_for_lines=True)]


def _plain(path: str, kind: str, text: str, *, hints_for_lines: bool) -> Document:
    regions: list[Region] = []
    cursor = 0
    lines = text.splitlines(keepends=True)
    if not lines and text == "":
        return Document(path, kind, "", [])
    for line_number, line in enumerate(lines or [text], 1):
        hints: set[str] = set()
        if hints_for_lines and _PAGE_MARK.match(line):
            hints.add("footer_page_mark")
        regions.append(
            Region(cursor, cursor + len(line), line_number, frozenset(hints))
        )
        cursor += len(line)
    return Document(path, kind, text, regions)


def _markdown(path: str, kind: str, text: str) -> Document:
    regions: list[Region] = []
    cursor = 0
    fenced = False
    for line_number, line in enumerate(text.splitlines(keepends=True), 1):
        if _FENCE.match(line):
            fenced = not fenced
            hints = frozenset({"fenced_code"})
        else:
            hints_set = {"fenced_code"} if fenced else set()
            if _PAGE_MARK.match(line):
                hints_set.add("footer_page_mark")
            hints = frozenset(hints_set)
        regions.append(Region(cursor, cursor + len(line), line_number, hints))
        cursor += len(line)
    return Document(path, kind, text, regions)


def _from_html(path: str, raw: str, file_kind: str) -> list[Document]:
    parser = _HtmlText()
    parser.feed(raw)
    parser.close()
    documents: list[Document] = []
    slide_kind = "narration" if file_kind == "narration" else "slide"
    if parser.slide_text.strip():
        documents.append(
            Document(path, slide_kind, parser.slide_text, parser.slide_regions)
        )
    if parser.narration_text.strip() and file_kind != "narration":
        documents.append(
            _plain(path, "narration", parser.narration_text, hints_for_lines=True)
        )
    elif parser.narration_text.strip() and file_kind == "narration":
        # File is already narration; keep embedded narration with the body.
        merged = parser.slide_text
        if parser.narration_text.strip():
            merged = (merged.rstrip() + "\n" + parser.narration_text).lstrip("\n")
        documents = [_plain(path, "narration", merged, hints_for_lines=True)]
    return documents


class _HtmlText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.slide_text = ""
        self.slide_regions: list[Region] = []
        self.narration_text = ""
        self._skip = 0
        self._narr = 0
        self._stack: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        self._stack.append((tag, attr))
        line, _ = self.getpos()
        if tag in {"script", "style", "noscript"}:
            if tag == "script" and attr.get("type", "").lower() == "application/x-narration":
                self._narr += 1
            else:
                self._skip += 1
        if tag in _BLOCK:
            self._append_slide("\n", line, frozenset())
        if self._skip or self._narr:
            return
        for key in ("alt", "title", "aria-label"):
            value = attr.get(key, "").strip()
            if value:
                self._append_slide(value + "\n", line, self._hints())
        narration = attr.get("data-narration", "").strip()
        if narration:
            self.narration_text += narration + "\n"

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._stack:
            self._stack.pop()
        line, _ = self.getpos()
        if tag in _BLOCK:
            self._append_slide("\n", line, frozenset())
        if tag in {"script", "style", "noscript"}:
            if self._narr and tag == "script":
                self._narr -= 1
            elif self._skip:
                self._skip -= 1

    def handle_data(self, data: str) -> None:
        line, _ = self.getpos()
        if self._narr:
            self.narration_text += data
            return
        if self._skip or data == "":
            return
        self._append_slide(data, line, self._hints())

    def _hints(self) -> frozenset[str]:
        hints: set[str] = set()
        for tag, attr in self._stack:
            ident = f"{attr.get('id', '')} {attr.get('class', '')}".lower()
            compact = ident.replace("-", "").replace("_", "")
            if "pagenumber" in compact or "pagenum" in compact or "slidenum" in compact:
                hints.add("page_chrome")
            if "footer" in ident or tag == "footer":
                hints.add("footer")
            if tag == "pre":
                hints.add("fenced_code")
        return frozenset(hints)

    def _append_slide(self, data: str, line: int, hints: frozenset[str]) -> None:
        stripped = data.strip()
        extra = set(hints)
        if "page_chrome" in hints:
            extra.add("page_chrome")
        if stripped and _PAGE_MARK.match(stripped) and ("footer" in hints or "page_chrome" in hints):
            extra.add("footer_page_mark")
        if stripped.isdigit() and "page_chrome" in hints:
            extra.add("page_chrome")
        start = len(self.slide_text)
        self.slide_text += data
        self.slide_regions.append(
            Region(start, start + len(data), line, frozenset(extra))
        )
