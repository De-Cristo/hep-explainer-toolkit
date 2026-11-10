"""Every number on a slide or in the narration must trace to a source.

Sources are declared in a YAML manifest: a HEPData record, a fit-result
JSON file, a datacard, or a paper/CDS/arXiv reference. Local JSON and
datacard files are opened and the declared value is checked. Remote
records are not downloaded.

Numbers that are not physics claims (slide indices, years, URLs, arXiv
ids, versions, fenced code) are exempt only when a rule in the allow
list says so, and every exemption is reported.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from checks.documents import discover, load_document
from checks.numbers import (
    NumberHit,
    canonical_unit,
    convert,
    extract_numbers,
    quantum_of,
)
from checks.yamlsubset import YamlError, load as load_yaml

_DEFAULT_ALLOW = Path(__file__).resolve().parent / "config" / "traceability_allow.yaml"
_ARXIV = re.compile(r"^\d{4}\.\d{4,5}$")
_NUMBER_TOKEN = re.compile(
    r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
)


class ManifestError(ValueError):
    """The manifest is missing a field or cites a file that is not usable."""


@dataclass
class MatchRule:
    rounding: str = "half_up"
    absolute: Decimal = Decimal(0)
    relative: Decimal = Decimal(0)


@dataclass
class AllowRule:
    id: str
    kind: str
    hints: frozenset[str] = frozenset()
    patterns: list[re.Pattern[str]] = field(default_factory=list)
    year_min: Decimal | None = None
    year_max: Decimal | None = None
    literals: frozenset[Decimal] = frozenset()


@dataclass
class Source:
    id: str
    value: Decimal
    quantum: Decimal
    unit: str | None
    uncertainty: Decimal | None
    uncertainty_quantum: Decimal | None
    uncertainty_up: Decimal | None
    uncertainty_down: Decimal | None
    origin: str
    process: str | None = None
    component: str | None = None
    quantity: str | None = None


@dataclass
class Manifest:
    path: Path
    match: MatchRule
    allows: list[AllowRule]
    sources: list[Source]
    inputs: list[tuple[Path, str]] | None
    source_errors: list[str]


@dataclass
class Exemption:
    rule_id: str
    path: str
    line: int
    kind: str
    value: str
    surface: str


@dataclass
class Match:
    path: str
    line: int
    kind: str
    value: str
    surface: str
    source_id: str
    origin: str


@dataclass
class Unmatched:
    path: str
    line: int
    kind: str
    value: str
    unit: str | None
    surface: str
    nearest: str


@dataclass
class Wording:
    path: str
    line: int
    kind: str
    surface: str
    message: str


@dataclass
class TraceReport:
    manifest: str
    failures: list[Unmatched]
    source_errors: list[str]
    exemptions: list[Exemption]
    matches: list[Match]
    wording: list[Wording] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures and not self.source_errors and not self.wording


def load_manifest(path: Path) -> Manifest:
    try:
        data = load_yaml(path.read_text(encoding="utf-8"))
    except (OSError, YamlError) as exc:
        raise ManifestError(f"cannot read manifest {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError("manifest must be a mapping")
    match = _match_rule(data.get("match") or {})
    allows = _allows(data)
    sources: list[Source] = []
    errors: list[str] = []
    for entry in data.get("sources") or []:
        source, error = _source(entry, path.parent, match)
        if source is not None:
            sources.append(source)
        if error:
            errors.append(error)
    inputs = _inputs(data.get("inputs"), path.parent) if "inputs" in data else None
    return Manifest(path, match, allows, sources, inputs, errors)


def check(
    root: Path,
    manifest_path: Path,
    *,
    inputs: list[tuple[Path, str]] | None = None,
) -> TraceReport:
    manifest = load_manifest(manifest_path)
    documents = _documents(root, manifest, inputs=inputs)
    exemptions: list[Exemption] = []
    matches: list[Match] = []
    failures: list[Unmatched] = []
    wording: list[Wording] = []
    for document in documents:
        for hit in extract_numbers(document):
            issue = _quantity_wording(hit)
            if issue is not None:
                wording.append(
                    Wording(hit.path, hit.line, hit.kind, " ".join(hit.surface.split()), issue)
                )
            rule_id = _exemption(hit, document.text, manifest.allows)
            if rule_id is not None:
                exemptions.append(
                    Exemption(
                        rule_id,
                        hit.path,
                        hit.line,
                        hit.kind,
                        _format_value(hit),
                        " ".join(hit.surface.split()),
                    )
                )
                continue
            source = _best_source(hit, manifest.sources, manifest.match)
            if source is None:
                failures.append(
                    Unmatched(
                        hit.path,
                        hit.line,
                        hit.kind,
                        _format_value(hit),
                        hit.unit,
                        " ".join(hit.surface.split()),
                        _nearest(hit, manifest.sources),
                    )
                )
                continue
            matches.append(
                Match(
                    hit.path,
                    hit.line,
                    hit.kind,
                    _format_value(hit),
                    " ".join(hit.surface.split()),
                    source.id,
                    source.origin,
                )
            )
    return TraceReport(
        manifest=manifest.path.as_posix(),
        failures=failures,
        source_errors=list(manifest.source_errors),
        exemptions=exemptions,
        matches=matches,
        wording=wording,
    )


def format_report(report: TraceReport, *, verbose: bool = False) -> str:
    status = "PASS" if report.ok else "FAIL"
    lines = [f"traceability: {status}", f"  manifest: {report.manifest}"]
    for failure in report.failures:
        nearest = f" nearest {failure.nearest}" if failure.nearest else ""
        lines.append(
            f"  FAIL {failure.kind:9} {failure.path}:{failure.line} "
            f"{failure.value} surface={failure.surface!r}{nearest}"
        )
    for error in report.source_errors:
        lines.append(f"  FAIL source {error}")
    for item in report.wording:
        lines.append(
            f"  FAIL wording {item.kind:9} {item.path}:{item.line} "
            f"{item.message} surface={item.surface!r}"
        )
    for item in report.exemptions:
        lines.append(
            f"  exempt {item.rule_id:16} {item.kind:9} {item.path}:{item.line} "
            f"{item.value} surface={item.surface!r}"
        )
    if verbose:
        for item in report.matches:
            lines.append(
                f"  ok {item.kind:9} {item.path}:{item.line} {item.value} "
                f"-> {item.source_id} ({item.origin})"
            )
    lines.append(
        f"  {len(report.failures)} unmatched, {len(report.wording)} wording, "
        f"{len(report.source_errors)} source error(s), "
        f"{len(report.exemptions)} exemption(s), {len(report.matches)} matched"
    )
    return "\n".join(lines)


def report_to_json(report: TraceReport) -> dict[str, object]:
    return {
        "manifest": report.manifest,
        "ok": report.ok,
        "unmatched": [item.__dict__ for item in report.failures],
        "source_errors": report.source_errors,
        "wording": [item.__dict__ for item in report.wording],
        "exemptions": [item.__dict__ for item in report.exemptions],
        "matches": [item.__dict__ for item in report.matches],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m checks.traceability",
        description="Check that slide and narration numbers trace to a source manifest.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    check_parser = sub.add_parser("check", help="check a deck directory")
    check_parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=None,
        help="deck directory (default: the manifest's directory)",
    )
    check_parser.add_argument("--manifest", type=Path, default=None)
    check_parser.add_argument("--json", action="store_true")
    check_parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest_path, root = _locate(args.path, args.manifest)
        report = check(root, manifest_path)
    except ManifestError as exc:
        print(f"traceability: error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report_to_json(report), indent=2))
    else:
        print(format_report(report, verbose=args.verbose))
    return 0 if report.ok else 1


def _locate(path: Path | None, manifest: Path | None) -> tuple[Path, Path]:
    if manifest is None:
        search = path or Path(".")
        if search.is_file():
            raise ManifestError("pass --manifest when the path is a file")
        for name in ("sources.yaml", "sources.yml"):
            candidate = search / name
            if candidate.is_file():
                manifest = candidate
                break
        else:
            raise ManifestError(
                f"no sources.yaml in {search}; pass --manifest"
            )
    assert manifest is not None
    if not manifest.is_file():
        raise ManifestError(f"manifest not found: {manifest}")
    root = path if path is not None else manifest.parent
    return manifest, root


def _documents(
    root: Path,
    manifest: Manifest,
    *,
    inputs: list[tuple[Path, str]] | None = None,
) -> list:
    documents = []
    pairs = inputs if inputs is not None else manifest.inputs
    if pairs is None:
        pairs = discover(root)
    root_resolved = root.resolve()
    for path, kind in pairs:
        if not path.is_file():
            raise ManifestError(f"missing {kind} file: {path}")
        loaded = load_document(path, kind)
        try:
            display = path.resolve().relative_to(root_resolved).as_posix()
        except ValueError:
            display = path.as_posix()
        for document in loaded:
            document.path = display
        documents.extend(loaded)
    return documents


def _match_rule(data: object) -> MatchRule:
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ManifestError("match: must be a mapping")
    rounding = str(data.get("rounding") or "half_up")
    if rounding not in {"half_up", "none"}:
        raise ManifestError("match.rounding must be half_up or none")
    return MatchRule(
        rounding=rounding,
        absolute=_plain_decimal(data.get("absolute_tolerance") or 0, "absolute_tolerance"),
        relative=_plain_decimal(data.get("relative_tolerance") or 0, "relative_tolerance"),
    )


def _allows(data: dict) -> list[AllowRule]:
    rules: list[AllowRule] = []
    if data.get("allow_defaults", True) is not False:
        try:
            defaults = load_yaml(_DEFAULT_ALLOW.read_text(encoding="utf-8"))
        except (OSError, YamlError) as exc:
            raise ManifestError(f"cannot read default allow list: {exc}") from exc
        rules.extend(_allow_entries((defaults or {}).get("allow") or [], "default allow"))
    rules.extend(_allow_entries(data.get("allow") or [], "manifest allow"))
    return rules


def _allow_entries(entries: object, where: str) -> list[AllowRule]:
    if not isinstance(entries, list):
        raise ManifestError(f"{where} must be a list")
    rules: list[AllowRule] = []
    for entry in entries:
        if not isinstance(entry, dict) or "id" not in entry or "kind" not in entry:
            raise ManifestError(f"{where} entry needs id and kind")
        kind = str(entry["kind"])
        hints = frozenset(str(item) for item in entry.get("hints") or [])
        patterns = [re.compile(str(pattern)) for pattern in entry.get("patterns") or []]
        literals = frozenset(
            _plain_decimal(item, f"allow {entry['id']}")
            for item in entry.get("values") or []
        )
        year_min = year_max = None
        if kind == "year":
            year_min = _plain_decimal(entry.get("min"), f"{entry['id']}.min")
            year_max = _plain_decimal(entry.get("max"), f"{entry['id']}.max")
        rules.append(
            AllowRule(
                id=str(entry["id"]),
                kind=kind,
                hints=hints,
                patterns=patterns,
                year_min=year_min,
                year_max=year_max,
                literals=literals,
            )
        )
    return rules


def _inputs(data: object, directory: Path) -> list[tuple[Path, str]]:
    if not isinstance(data, dict):
        raise ManifestError("inputs must be a mapping")
    pairs: list[tuple[Path, str]] = []
    for kind in ("slides", "narration"):
        for item in data.get(kind) or []:
            path = Path(str(item))
            if not path.is_absolute():
                path = directory / path
            pairs.append((path, "slide" if kind == "slides" else "narration"))
    return pairs


def _source(entry: object, directory: Path, match: MatchRule) -> tuple[Source | None, str | None]:
    if not isinstance(entry, dict) or "id" not in entry:
        raise ManifestError(f"source entry needs an id: {entry!r}")
    source_id = str(entry["id"])
    if "value" not in entry:
        raise ManifestError(f"source {source_id} needs a value")
    value, quantum = _decimal_and_quantum(entry["value"], f"{source_id}.value")
    unit = None
    if entry.get("unit") not in (None, ""):
        unit = canonical_unit(str(entry["unit"]))
        if unit is None:
            unit = str(entry["unit"]).strip()
    uncertainty = uncertainty_quantum = None
    if entry.get("uncertainty") is not None:
        uncertainty, uncertainty_quantum = _decimal_and_quantum(
            entry["uncertainty"], f"{source_id}.uncertainty"
        )
    uncertainty_up = uncertainty_down = None
    if entry.get("uncertainty_up") is not None or entry.get("uncertainty_down") is not None:
        if entry.get("uncertainty_up") is None or entry.get("uncertainty_down") is None:
            raise ManifestError(f"source {source_id} needs both uncertainty_up and uncertainty_down")
        uncertainty_up, _ = _decimal_and_quantum(entry["uncertainty_up"], f"{source_id}.uncertainty_up")
        uncertainty_down, _ = _decimal_and_quantum(
            entry["uncertainty_down"], f"{source_id}.uncertainty_down"
        )
    origin_map = entry.get("source")
    if not isinstance(origin_map, dict) or "type" not in origin_map:
        raise ManifestError(f"source {source_id} needs source.type")
    process = str(entry["process"]).upper() if entry.get("process") else None
    component = str(entry["kind"]).lower() if entry.get("kind") else None
    if component is not None and component not in {"central", "stat", "syst", "total"}:
        raise ManifestError(
            f"source {source_id} kind must be central, stat, syst, or total"
        )
    quantity = str(entry["quantity"]).lower() if entry.get("quantity") else None
    origin, error = _origin(source_id, origin_map, directory, value, quantum, uncertainty, match)
    source = Source(
        id=source_id,
        value=value,
        quantum=quantum,
        unit=unit,
        uncertainty=uncertainty,
        uncertainty_quantum=uncertainty_quantum,
        uncertainty_up=uncertainty_up,
        uncertainty_down=uncertainty_down,
        origin=origin,
        process=process,
        component=component,
        quantity=quantity,
    )
    return source, error


def _origin(
    source_id: str,
    origin_map: dict,
    directory: Path,
    value: Decimal,
    quantum: Decimal,
    uncertainty: Decimal | None,
    match: MatchRule,
) -> tuple[str, str | None]:
    kind = str(origin_map["type"])
    if kind == "hepdata":
        record = str(origin_map.get("record") or "").strip()
        if record == "":
            raise ManifestError(f"source {source_id} hepdata record is empty")
        lowered = record.lower()
        if not (
            lowered.startswith("http://")
            or lowered.startswith("https://")
            or "hepdata" in lowered
            or record.isdigit()
        ):
            raise ManifestError(
                f"source {source_id} hepdata record must be a URL, an id, or contain 'hepdata'"
            )
        table = origin_map.get("table")
        extra = f" table {table}" if table else ""
        return f"HEPData {record}{extra}", None
    if kind == "paper":
        return _paper_origin(source_id, origin_map), None
    if kind == "fit_json":
        return _fit_origin(source_id, origin_map, directory, value, quantum, uncertainty, match)
    if kind == "datacard":
        return _datacard_origin(source_id, origin_map, directory, value, quantum, match)
    raise ManifestError(
        f"source {source_id} has unknown type {kind!r} "
        "(expected hepdata, fit_json, datacard, or paper)"
    )


def _paper_origin(source_id: str, origin_map: dict) -> str:
    parts: list[str] = []
    arxiv = origin_map.get("arxiv")
    cds = origin_map.get("cds")
    doi = origin_map.get("doi")
    url = origin_map.get("url")
    if arxiv:
        if not _ARXIV.fullmatch(str(arxiv).strip()):
            raise ManifestError(f"source {source_id} arxiv id {arxiv!r} is not NNNN.NNNNN")
        parts.append(f"arXiv:{arxiv}")
    if cds:
        parts.append(f"CDS {cds}")
    if doi:
        if not str(doi).startswith("10."):
            raise ManifestError(f"source {source_id} doi must start with 10.")
        parts.append(f"doi:{doi}")
    if url:
        if not str(url).lower().startswith(("http://", "https://")):
            raise ManifestError(f"source {source_id} paper url must be http(s)")
        parts.append(str(url))
    if not parts:
        raise ManifestError(f"source {source_id} paper needs arxiv, cds, doi, or url")
    return "paper " + ", ".join(parts)


def _fit_origin(
    source_id: str,
    origin_map: dict,
    directory: Path,
    value: Decimal,
    quantum: Decimal,
    uncertainty: Decimal | None,
    match: MatchRule,
) -> tuple[str, str | None]:
    file_path = _existing_file(source_id, origin_map.get("path"), directory)
    key = str(origin_map.get("key") or "").strip()
    if key == "":
        raise ManifestError(f"source {source_id} fit_json needs a key")
    origin = f"fit_json {file_path.name} key {key}"
    try:
        payload = json.loads(
            file_path.read_text(encoding="utf-8"),
            parse_float=Decimal,
            parse_int=Decimal,
        )
        found = _dig(payload, key)
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        return origin, f"{source_id}: cannot read {file_path.name} key {key} ({exc})"
    found_decimal = _coerce_number(found, f"{source_id} file value")
    if not _values_agree(value, quantum, found_decimal, match):
        return origin, (
            f"{source_id}: manifest value {value} but {file_path.name} key {key} is {found_decimal}"
        )
    unc_key = origin_map.get("uncertainty_key")
    if uncertainty is not None and unc_key:
        try:
            found_unc = _coerce_number(_dig(payload, str(unc_key)), f"{source_id} uncertainty")
        except (KeyError, ValueError) as exc:
            return origin, f"{source_id}: uncertainty key {unc_key} ({exc})"
        unc_quantum = quantum_of(uncertainty)
        if not _values_agree(uncertainty, unc_quantum, found_unc, match):
            return origin, (
                f"{source_id}: manifest uncertainty {uncertainty} but {file_path.name} "
                f"key {unc_key} is {found_unc}"
            )
    return origin, None


def _datacard_origin(
    source_id: str,
    origin_map: dict,
    directory: Path,
    value: Decimal,
    quantum: Decimal,
    match: MatchRule,
) -> tuple[str, str | None]:
    file_path = _existing_file(source_id, origin_map.get("path"), directory)
    key = str(origin_map.get("key") or "").strip()
    if key == "":
        raise ManifestError(f"source {source_id} datacard needs a key")
    index = int(origin_map.get("index") or 0)
    origin = f"datacard {file_path.name} key {key}[{index}]"
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return origin, f"{source_id}: cannot read {file_path.name} ({exc})"
    numbers = _datacard_numbers(text, key)
    if index >= len(numbers):
        return origin, (
            f"{source_id}: {file_path.name} key {key} has {len(numbers)} number(s), "
            f"index {index} is missing"
        )
    found = numbers[index]
    if not _values_agree(value, quantum, found, match):
        return origin, (
            f"{source_id}: manifest value {value} but {file_path.name} key {key}[{index}] is {found}"
        )
    return origin, None


def _existing_file(source_id: str, raw: object, directory: Path) -> Path:
    if raw in (None, ""):
        raise ManifestError(f"source {source_id} is missing a path")
    path = Path(str(raw))
    if not path.is_absolute():
        path = directory / path
    if not path.is_file():
        raise ManifestError(f"source {source_id}: file not found: {path}")
    if path.stat().st_size > 5_000_000:
        raise ManifestError(f"source {source_id}: {path.name} is larger than 5 MB")
    return path


def _dig(payload: object, key: str) -> object:
    current = payload
    for part in key.split("."):
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(part)
            current = current[part]
        elif isinstance(current, list):
            current = current[int(part)]
        else:
            raise KeyError(part)
    return current


def _datacard_numbers(text: str, key: str) -> list[Decimal]:
    found: list[Decimal] = []
    for line in text.splitlines():
        body = line.split("#", 1)[0].strip()
        if body == "":
            continue
        tokens = body.replace("=", " ").replace(":", " ").split()
        if not tokens or tokens[0].lower() != key.lower():
            continue
        for token in tokens[1:]:
            if _NUMBER_TOKEN.fullmatch(token):
                found.append(Decimal(token))
    return found


def _values_agree(
    declared: Decimal, quantum: Decimal, found: Decimal, match: MatchRule
) -> bool:
    return _close(declared, found, quantum, match)


def _exemption(hit: NumberHit, text: str, rules: list[AllowRule]) -> str | None:
    for rule in rules:
        if _rule_matches(hit, text, rule):
            return rule.id
    return None


def _rule_matches(hit: NumberHit, text: str, rule: AllowRule) -> bool:
    if rule.kind == "year":
        if hit.unit or hit.uncertainty is not None or hit.uncertainty_up is not None:
            return False
        if hit.quantum != 1:
            return False
        if hit.value != hit.value.to_integral_value():
            return False
        assert rule.year_min is not None and rule.year_max is not None
        return rule.year_min <= hit.value <= rule.year_max
    if rule.kind == "literal":
        if hit.unit or hit.uncertainty is not None:
            return False
        return hit.value in rule.literals
    if rule.kind not in {"slide_index", "context", "hints"}:
        raise ManifestError(f"unknown allow kind {rule.kind!r}")
    if hit.hints & rule.hints:
        return True
    for pattern in rule.patterns:
        for match in pattern.finditer(text):
            if match.start() <= hit.start and hit.end <= match.end():
                return True
    return False


def _best_source(hit: NumberHit, sources: list[Source], match: MatchRule) -> Source | None:
    found: list[tuple[int, int, Source]] = []
    for index, source in enumerate(sources):
        rank = _rank(hit, source)
        if rank >= 99:
            continue
        if _source_matches(hit, source, match):
            found.append((rank, index, source))
    if not found:
        return None
    found.sort()
    return found[0][2]


def _rank(hit: NumberHit, source: Source) -> int:
    if hit.unit and source.unit:
        if hit.unit == source.unit:
            return 0
        if convert(Decimal(1), source.unit, hit.unit) is None:
            return 99
        return 0
    if hit.unit or source.unit:
        return 1
    return 0


_XSEC_UNITS = {"fb", "pb", "nb", "ub", "mb"}


def _quantity_wording(hit: NumberHit) -> str | None:
    """Signal strength must not be called a cross section or given a unit.

    Other wording mistakes (the wrong channel name, observed versus
    expected, a synonym we do not list) are not detected.
    """
    if not hit.calls_signal:
        return None
    if hit.calls_cross_section and hit.unit in _XSEC_UNITS:
        return "signal strength called a cross section and given a cross-section unit"
    if hit.calls_cross_section:
        return "signal strength called a cross section"
    if hit.unit in _XSEC_UNITS:
        return "signal strength given a cross-section unit"
    return None


def _context_ok(hit: NumberHit, source: Source) -> bool:
    if source.process and hit.process and source.process.upper() != hit.process.upper():
        return False
    if hit.component and source.component and hit.component != source.component:
        return False
    if hit.component and source.component is None:
        return False
    if source.component in {"stat", "syst", "total"} and hit.component != source.component:
        return False
    if source.component == "central" and hit.component not in {None, "central"}:
        return False
    if source.quantity in {"mu", "signal_strength"} and hit.unit:
        return False
    if hit.quantity and source.quantity and hit.quantity != source.quantity:
        return False
    return True


def _source_matches(hit: NumberHit, source: Source, match: MatchRule) -> bool:
    if not _context_ok(hit, source):
        return False
    converted = _into_shown(source.value, source.unit, hit.unit)
    if converted is None or not _close(hit.value, converted, hit.quantum, match):
        return False
    if hit.uncertainty is not None:
        if source.uncertainty is None:
            return False
        unc = _into_shown(source.uncertainty, source.unit, hit.unit)
        quantum = hit.uncertainty_quantum or hit.quantum
        if unc is None or not _close(hit.uncertainty, unc, quantum, match):
            return False
    if hit.uncertainty_up is not None or hit.uncertainty_down is not None:
        if source.uncertainty_up is None or source.uncertainty_down is None:
            return False
        up = _into_shown(source.uncertainty_up, source.unit, hit.unit)
        down = _into_shown(source.uncertainty_down, source.unit, hit.unit)
        up_q = hit.uncertainty_up_quantum or hit.quantum
        down_q = hit.uncertainty_down_quantum or hit.quantum
        if (
            up is None
            or down is None
            or hit.uncertainty_up is None
            or hit.uncertainty_down is None
            or not _close(hit.uncertainty_up, up, up_q, match)
            or not _close(hit.uncertainty_down, down, down_q, match)
        ):
            return False
    return True


def _into_shown(value: Decimal, source_unit: str | None, shown_unit: str | None) -> Decimal | None:
    if shown_unit is None or source_unit is None or shown_unit == source_unit:
        return value
    return convert(value, source_unit, shown_unit)


def _close(shown: Decimal, candidate: Decimal, quantum: Decimal, match: MatchRule) -> bool:
    if match.rounding == "half_up":
        try:
            rounded = candidate.quantize(quantum, rounding=ROUND_HALF_UP)
        except (ValueError, ArithmeticError):
            rounded = None
        if rounded is not None and rounded == shown:
            return True
    tolerance = max(match.absolute, match.relative * abs(candidate))
    return abs(shown - candidate) <= tolerance


def _nearest(hit: NumberHit, sources: list[Source]) -> str:
    best: tuple[Decimal, str] | None = None
    for source in sources:
        if source.process and hit.process and source.process.upper() != hit.process.upper():
            continue
        if source.component and hit.component and source.component != hit.component:
            continue
        if hit.component in {"stat", "syst", "total"} and source.component != hit.component:
            continue
        if _rank(hit, source) >= 99:
            continue
        converted = _into_shown(source.value, source.unit, hit.unit)
        if converted is None:
            continue
        distance = abs(hit.value - converted)
        label = f"{source.id}={source.value}"
        if source.unit:
            label += f" {source.unit}"
        label += f" |Δ|={distance}"
        if best is None or distance < best[0]:
            best = (distance, label)
    return "" if best is None else best[1]


def _format_value(hit: NumberHit) -> str:
    text = format(hit.value, "f")
    if hit.uncertainty is not None:
        text += f" ± {format(hit.uncertainty, 'f')}"
    elif hit.uncertainty_up is not None and hit.uncertainty_down is not None:
        text += f" +{format(hit.uncertainty_up, 'f')}/-{format(hit.uncertainty_down, 'f')}"
    if hit.unit:
        text += f" {hit.unit}"
    return text


def _plain_decimal(value: object, label: str) -> Decimal:
    number, _ = _decimal_and_quantum(value, label)
    return number


def _decimal_and_quantum(value: object, label: str) -> tuple[Decimal, Decimal]:
    if isinstance(value, bool) or value is None:
        raise ManifestError(f"{label} is not a number")
    if isinstance(value, int):
        return Decimal(value), Decimal(1)
    if isinstance(value, Decimal):
        return value, quantum_of(value)
    if isinstance(value, str):
        try:
            number = Decimal(value)
        except Exception as exc:
            raise ManifestError(f"{label} is not a number") from exc
        return number, quantum_of(number)
    raise ManifestError(f"{label} is not a number")


def _coerce_number(value: object, label: str) -> Decimal:
    number, _ = _decimal_and_quantum(value, label)
    return number


if __name__ == "__main__":
    raise SystemExit(main())
