"""Confidentiality gate for a deck or project folder.

Scans HTML (including text split by tags), Markdown, narration, SVG,
plain text, PDF text operators, image filenames, and cheap image
metadata. Phrases, CADI codes, note numbers, and private-link patterns
live in ``config/markers.yaml``. One configured label is a warning.
One configured label fails unless the project allows that rule id.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import html
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from checks.imagemeta import metadata_strings
from checks.pdftext import extract_pdf_text
from checks.yamlsubset import YamlError, load as load_yaml

_DEFAULT_CONFIG = Path(__file__).resolve().parent / "config" / "markers.yaml"
_DATA_URI = re.compile(
    rb"data:image/(png|jpe?g|gif|webp);base64,([A-Za-z0-9+/=\r\n]+)",
    re.IGNORECASE,
)
_MARKUP = {".html", ".htm", ".svg", ".xml"}


@dataclass
class Rule:
    id: str
    severity: str
    allowable: bool
    patterns: list[re.Pattern[str]]
    kind: str  # "phrase", "regex", or "cadi"


@dataclass
class Config:
    max_file_bytes: int
    exclude_dir_names: set[str]
    skip_paths: list[str]
    exempt_paths: list[str]
    text_extensions: set[str]
    image_extensions: set[str]
    pdf_extensions: set[str]
    rules: list[Rule]
    cadi_templates: list[str]


@dataclass
class AllowList:
    markers: set[str] = field(default_factory=set)
    public_cadi: dict[str, str] = field(default_factory=dict)
    source: str = ""


@dataclass
class Finding:
    severity: str
    rule_id: str
    path: str
    line: int | None
    channel: str
    snippet: str
    note: str = ""
    quiet: bool = False


@dataclass
class Report:
    root: str
    findings: list[Finding]
    allow_source: str = ""

    @property
    def failures(self) -> list[Finding]:
        return [item for item in self.findings if item.severity == "fail"]

    @property
    def warnings(self) -> list[Finding]:
        return [item for item in self.findings if item.severity == "warn"]

    def ok(self, *, strict: bool = False) -> bool:
        if self.failures:
            return False
        if strict and self.warnings:
            return False
        return True


class ConfigError(ValueError):
    """The marker file or an allow file cannot be used."""


def default_config_path() -> Path:
    return _DEFAULT_CONFIG


def load_config(path: Path | None = None) -> Config:
    config_path = path or _DEFAULT_CONFIG
    try:
        data = load_yaml(config_path.read_text(encoding="utf-8"))
    except (OSError, YamlError) as exc:
        raise ConfigError(f"cannot read marker config {config_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("marker config must be a mapping")
    rules: list[Rule] = []
    for entry in data.get("rules") or []:
        rules.append(_rule_from_mapping(entry))
    cadi = data.get("cadi") or {}
    if cadi:
        groups = [str(group) for group in cadi.get("groups") or []]
        if not groups:
            raise ConfigError("cadi.groups is empty")
        group_re = "|".join(re.escape(group) for group in groups)
        pattern = (
            rf"(?<![A-Za-z0-9-])((?:{group_re})-(?:\d{{2}}|\d{{4}})-\d{{3}})(?!\d)"
        )
        rules.append(
            Rule(
                id="cadi_line",
                severity=str(cadi.get("severity") or "fail"),
                allowable=False,
                patterns=[re.compile(pattern, re.IGNORECASE)],
                kind="cadi",
            )
        )
    for entry in data.get("urls") or []:
        rules.append(_rule_from_mapping(entry, kind="regex"))
    return Config(
        max_file_bytes=int(data.get("max_file_bytes") or 80_000_000),
        exclude_dir_names={str(name) for name in data.get("exclude_dir_names") or []},
        skip_paths=[str(item) for item in data.get("skip_paths") or []],
        exempt_paths=[str(item) for item in data.get("exempt_paths") or []],
        text_extensions={str(item).lower() for item in data.get("text_extensions") or []},
        image_extensions={str(item).lower() for item in data.get("image_extensions") or []},
        pdf_extensions={str(item).lower() for item in data.get("pdf_extensions") or []},
        rules=rules,
        cadi_templates=[str(item) for item in (cadi.get("public_id_templates") or [])],
    )


def load_allow(path: Path) -> AllowList:
    try:
        data = load_yaml(path.read_text(encoding="utf-8"))
    except (OSError, YamlError) as exc:
        raise ConfigError(f"cannot read allow file {path}: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError("allow file must be a mapping")
    markers = {str(item) for item in data.get("allow_markers") or []}
    public: dict[str, str] = {}
    for entry in data.get("public_cadi") or []:
        if not isinstance(entry, dict) or "code" not in entry or "reference" not in entry:
            raise ConfigError("public_cadi entries need code and reference")
        reference = str(entry["reference"]).strip()
        if reference == "":
            raise ConfigError("public_cadi reference is empty")
        public[_normalize_code(str(entry["code"]))] = reference
    return AllowList(markers=markers, public_cadi=public, source=path.as_posix())


def scan(
    root: Path,
    config: Config | None = None,
    allow: AllowList | None = None,
) -> Report:
    """Scan ``root`` (a file or a directory) and return every hit."""
    config = config or load_config()
    root = root.resolve()
    if allow is None:
        candidate = root / "confidentiality-allow.yaml"
        if root.is_dir() and candidate.is_file():
            allow = load_allow(candidate)
        else:
            allow = AllowList()
    findings: list[Finding] = []
    skipped_files: set[Path] = set()
    if allow.source:
        skipped_files.add(Path(allow.source).resolve())
    if root.is_file():
        files = [root]
        base = root.parent
    else:
        files = list(_iter_files(root, config))
        base = root
    for path in files:
        if path.resolve() in skipped_files:
            continue
        rel = _relative(path, base)
        if _matches_prefix(rel, config.skip_paths):
            continue
        findings.extend(_scan_file(path, rel, config, allow))
    return Report(root=str(root), findings=findings, allow_source=allow.source)


def format_report(report: Report, *, verbose: bool = False) -> str:
    failures = report.failures
    warnings = report.warnings
    loud = [
        item
        for item in report.findings
        if item.severity == "exempt" and not item.quiet
    ]
    quiet = [
        item
        for item in report.findings
        if item.severity == "exempt" and item.quiet
    ]
    status = "PASS" if not failures else "FAIL"
    lines = [
        f"confidentiality: {status}",
        f"  root: {report.root}",
    ]
    if report.allow_source:
        lines.append(f"  allow file: {report.allow_source}")
    for finding in failures + warnings + loud:
        lines.append(_format_finding(finding))
    if verbose:
        for finding in quiet:
            lines.append(_format_finding(finding))
    elif quiet:
        lines.append(
            f"  exemptions kept quiet: {len(quiet)} policy-document hit(s); --verbose lists them"
        )
    lines.append(
        f"  {len(failures)} failure(s), {len(warnings)} warning(s), "
        f"{len(loud) + len(quiet)} exemption(s)"
    )
    return "\n".join(lines)


def report_to_json(report: Report) -> dict[str, object]:
    return {
        "root": report.root,
        "allow_file": report.allow_source,
        "failures": len(report.failures),
        "warnings": len(report.warnings),
        "findings": [
            {
                "severity": item.severity,
                "rule": item.rule_id,
                "path": item.path,
                "line": item.line,
                "channel": item.channel,
                "snippet": item.snippet,
                "note": item.note,
            }
            for item in report.findings
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m checks.confidentiality",
        description="Fail a deck that still carries internal CMS markers.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    scan_parser = sub.add_parser("scan", help="scan a file or directory")
    scan_parser.add_argument("path", type=Path)
    scan_parser.add_argument("--config", type=Path, default=None)
    scan_parser.add_argument("--allow-file", type=Path, default=None)
    scan_parser.add_argument(
        "--allow-marker",
        action="append",
        default=[],
        help="rule id that is explicitly allowed (repeatable). "
        "Used for markers marked allowable in the config, such as work_in_progress.",
    )
    scan_parser.add_argument("--json", action="store_true")
    scan_parser.add_argument("--verbose", action="store_true")
    scan_parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 on warnings as well as failures",
    )
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        allow = _resolve_allow(args.path, args.allow_file, args.allow_marker)
        report = scan(args.path, config, allow)
    except ConfigError as exc:
        print(f"confidentiality: error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report_to_json(report), indent=2))
    else:
        print(format_report(report, verbose=args.verbose))
    return 0 if report.ok(strict=args.strict) else 1


def _resolve_allow(root: Path, allow_file: Path | None, markers: list[str]) -> AllowList:
    if allow_file is None:
        candidate = root / "confidentiality-allow.yaml"
        if root.is_dir() and candidate.is_file():
            allow_file = candidate
    allow = load_allow(allow_file) if allow_file is not None else AllowList()
    allow.markers.update(markers)
    return allow


def _rule_from_mapping(entry: object, kind: str | None = None) -> Rule:
    if not isinstance(entry, dict) or "id" not in entry:
        raise ConfigError(f"rule is missing an id: {entry!r}")
    rule_id = str(entry["id"])
    severity = str(entry.get("severity") or "fail")
    if severity not in {"fail", "warn"}:
        raise ConfigError(f"rule {rule_id} has unknown severity {severity}")
    patterns: list[re.Pattern[str]] = []
    if entry.get("regex"):
        patterns.append(re.compile(str(entry["regex"]), re.IGNORECASE))
        resolved_kind = kind or "regex"
    else:
        phrases = entry.get("patterns") or []
        if not phrases:
            raise ConfigError(f"rule {rule_id} has no patterns")
        for phrase in phrases:
            patterns.append(_phrase_pattern(str(phrase)))
        resolved_kind = kind or "phrase"
    return Rule(
        id=rule_id,
        severity=severity,
        allowable=bool(entry.get("allowable") or False),
        patterns=patterns,
        kind=resolved_kind,
    )


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    parts = phrase.split()
    if not parts:
        raise ConfigError("empty phrase")
    body = r"\s+".join(re.escape(part) for part in parts)
    return re.compile(rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])", re.IGNORECASE)


def _iter_files(root: Path, config: Config) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if not name.startswith(".") and name not in config.exclude_dir_names
        ]
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            found.append(Path(dirpath) / name)
    return found


def _scan_file(path: Path, rel: str, config: Config, allow: AllowList) -> list[Finding]:
    findings: list[Finding] = []
    exempt = _matches_prefix(rel, config.exempt_paths)
    suffix = path.suffix.lower()
    try:
        size = path.stat().st_size
    except OSError as exc:
        return [
            Finding("fail", "unreadable", rel, None, "file", path.name, note=str(exc))
        ]
    truncated = size > config.max_file_bytes
    # Filenames are scanned even when the bytes are skipped.
    findings.extend(
        _apply(path.stem.replace("_", " ").replace("-", " "), rel, None, "filename", config, allow, phrases_only=True)
    )
    findings.extend(
        _apply(path.name, rel, None, "filename", config, allow, phrases_only=False, regex_only=True)
    )
    if suffix in config.image_extensions:
        data = _read_bytes(path, config.max_file_bytes)
        for channel, text in metadata_strings(data, suffix.lstrip(".")):
            findings.extend(_apply(text, rel, None, channel, config, allow))
    elif suffix in config.pdf_extensions:
        data = _read_bytes(path, config.max_file_bytes)
        text = extract_pdf_text(data)
        findings.extend(_apply(text, rel, None, "pdf", config, allow))
    elif suffix in config.text_extensions or suffix == "":
        data = _read_bytes(path, config.max_file_bytes)
        decoded = data.decode("utf-8", errors="replace")
        findings.extend(_scan_text(decoded, rel, suffix, config, allow))
        findings.extend(_scan_data_uris(data, rel, config, allow))
    if truncated:
        findings.append(
            Finding(
                "warn",
                "truncated",
                rel,
                None,
                "file",
                path.name,
                note=f"file is {size} bytes; only the first {config.max_file_bytes} were scanned",
            )
        )
    if exempt:
        for finding in findings:
            if finding.severity in {"fail", "warn"}:
                finding.severity = "exempt"
                finding.note = "exempt path (policy document or marker list)"
            finding.quiet = True
    return _dedupe(findings)


def _scan_text(
    text: str, rel: str, suffix: str, config: Config, allow: AllowList
) -> list[Finding]:
    normalized = _normalize(html.unescape(text))
    findings = _apply(normalized, rel, None, "text", config, allow, track_lines=True)
    if suffix in _MARKUP:
        flat = _normalize(_flatten_markup(text))
        extra = _apply(flat, rel, None, "html-text", config, allow, track_lines=True)
        seen = {_snippet_key(item.snippet) + "\0" + item.rule_id for item in findings}
        for item in extra:
            key = _snippet_key(item.snippet) + "\0" + item.rule_id
            if key not in seen:
                findings.append(item)
                seen.add(key)
    return findings


def _scan_data_uris(data: bytes, rel: str, config: Config, allow: AllowList) -> list[Finding]:
    findings: list[Finding] = []
    for match in _DATA_URI.finditer(data):
        kind = match.group(1).decode("ascii").lower()
        if kind == "jpg":
            kind = "jpeg"
        payload = re.sub(rb"\s+", b"", match.group(2))
        if len(payload) > 3_000_000:
            findings.append(
                Finding(
                    "warn",
                    "truncated",
                    rel,
                    None,
                    f"embedded-{kind}",
                    "data-uri",
                    note="embedded image exceeded the metadata decode cap",
                )
            )
            continue
        try:
            decoded = base64.b64decode(payload, validate=False)
        except (ValueError, binascii.Error):
            continue
        for channel, text in metadata_strings(decoded, kind):
            findings.extend(
                _apply(text, rel, None, f"embedded-{channel}", config, allow)
            )
    return findings


def _apply(
    text: str,
    rel: str,
    line: int | None,
    channel: str,
    config: Config,
    allow: AllowList,
    *,
    phrases_only: bool = False,
    regex_only: bool = False,
    track_lines: bool = False,
) -> list[Finding]:
    if text.strip() == "":
        return []
    normalized = _normalize(text)
    raw_hits: list[tuple[Rule, re.Match[str]]] = []
    for rule in config.rules:
        if phrases_only and rule.kind != "phrase":
            continue
        if regex_only and rule.kind == "phrase":
            continue
        for pattern in rule.patterns:
            for match in pattern.finditer(normalized):
                raw_hits.append((rule, match))
    raw_hits = _drop_overlaps(raw_hits)
    findings: list[Finding] = []
    for rule, match in raw_hits:
        snippet = " ".join(match.group(0).split())
        hit_line = line
        if track_lines:
            hit_line = normalized.count("\n", 0, match.start()) + 1
        severity = rule.severity
        note = ""
        quiet = False
        if rule.kind == "cadi":
            code = _normalize_code(match.group(1))
            cleared = _public_reference(normalized, code, config.cadi_templates)
            if cleared:
                severity = "exempt"
                note = f"public reference in the same file: {cleared}"
            elif code in allow.public_cadi:
                severity = "exempt"
                note = f"explicit public reference: {allow.public_cadi[code]}"
        if severity != "exempt" and rule.allowable and _marker_allowed(rule, allow):
            severity = "exempt"
            note = "explicitly allowed"
        findings.append(
            Finding(severity, rule.id, rel, hit_line, channel, snippet, note, quiet)
        )
    return findings


def _drop_overlaps(
    hits: list[tuple[Rule, re.Match[str]]],
) -> list[tuple[Rule, re.Match[str]]]:
    """Keep the longest match when two phrases cover the same span."""
    ordered = sorted(hits, key=lambda item: (item[1].start(), -(item[1].end() - item[1].start())))
    kept: list[tuple[Rule, re.Match[str]]] = []
    for rule, match in ordered:
        if any(
            previous.start() <= match.start() and match.end() <= previous.end()
            for _, previous in kept
        ):
            continue
        kept.append((rule, match))
    return kept


def _public_reference(text: str, code: str, templates: list[str]) -> str | None:
    for template in templates:
        needle = template.format(code=code)
        if re.search(re.escape(needle), text, re.IGNORECASE):
            return needle
    return None


def _marker_allowed(rule: Rule, allow: AllowList) -> bool:
    allowed = {item.casefold() for item in allow.markers}
    return rule.id.casefold() in allowed


def _normalize(text: str) -> str:
    return (
        text.replace("\u00a0", " ")
        .replace("\u2009", " ")
        .replace("\u2212", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )


def _flatten_markup(text: str) -> str:
    """Drop tags. Inline tags disappear so a label split by <em> still reads."""
    without_code = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", "\n", text)

    def replace(match: re.Match[str]) -> str:
        name_match = re.match(r"(?is)</?\s*([a-z0-9]+)", match.group(0))
        name = name_match.group(1).lower() if name_match else ""
        if name in {
            "em",
            "span",
            "b",
            "i",
            "strong",
            "sup",
            "sub",
            "a",
            "code",
            "mark",
            "small",
            "u",
        }:
            return ""
        return " "

    flattened = re.sub(r"(?s)<[^>]+>", replace, without_code)
    return html.unescape(flattened)


def _normalize_code(code: str) -> str:
    cleaned = code.strip().upper()
    cleaned = re.sub(r"[\s/–—]+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned


def _matches_prefix(rel: str, prefixes: list[str]) -> bool:
    rel = rel.replace("\\", "/")
    for prefix in prefixes:
        prefix = prefix.replace("\\", "/").strip("/")
        if rel == prefix or rel.startswith(prefix + "/"):
            return True
    return False


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _read_bytes(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        return handle.read(limit)


def _snippet_key(snippet: str) -> str:
    return " ".join(snippet.split()).casefold()


def _dedupe(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple[str, str, str, str]] = set()
    unique: list[Finding] = []
    for finding in findings:
        key = (
            finding.rule_id,
            finding.channel,
            finding.path,
            _snippet_key(finding.snippet),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return unique


def _format_finding(finding: Finding) -> str:
    where = finding.path
    if finding.line:
        where = f"{where}:{finding.line}"
    note = f" ({finding.note})" if finding.note else ""
    return (
        f"  {finding.severity.upper():6} {finding.rule_id:20} {where} "
        f"[{finding.channel}] {finding.snippet}{note}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
