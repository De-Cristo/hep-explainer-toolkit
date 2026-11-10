"""Find numbers in slide text and narration, including spoken forms.

The extractor is deliberately literal. A lone small word such as "two"
is not a claim unless a unit or an uncertainty follows it. Commas are
thousands separators. Rounding uses the last digit the author actually
wrote, so "1.2" has quantum 0.1 and "1.2e-3" has quantum 0.0001.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from checks.documents import Document

_ONES = {
    "zero": 0,
    "oh": 0,
    "nought": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
}
_TEENS = {
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_SCALES = {
    "hundred": 100,
    "thousand": 1_000,
    "million": 1_000_000,
    "billion": 1_000_000_000,
}
_WORD = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)?")
_VERSION = re.compile(r"\d+(?:\.\d+){2,}")
_TIMES = re.compile(
    r"""(?x)
    (?P<sign>[-−+])?
    (?P<whole>\d+)
    (?:\.(?P<frac>\d+))?
    \s*(?:\\times|×|\*)\s*
    10\s*\^\s*\{?\s*(?P<exp>[-−+]?\d+)\s*\}?
    """
)
_NUM = re.compile(
    r"""(?x)
    (?P<sign>[-−+])?
    (?P<body>\d{1,3}(?:,\d{3})+|\d+)
    (?:\.(?P<frac>\d+))?
    (?:[eE](?P<exp>[-−+]?\d+))?
    """
)
_PM = re.compile(r"(?i)\s*(?:±|\+/-|\+-|plus[\s-]or[\s-]minus)\s*")
_LABELLED_PIECE = re.compile(
    r"""(?ix)
    \s*(?:±|\+/-|\+-)
    \s*(?P<num>\d+(?:\.\d+)?)
    (?:\s*\(\s*(?P<label>stat|syst|statistical|systematic|total)\s*\))?
    """
)
_PROCESS = re.compile(r"\b(WH|ZH|ttH|tH|ggH|VBF|VH|bbH)\b", re.IGNORECASE)
_CROSS_SECTION = re.compile(r"cross[\s-]+section", re.IGNORECASE)
_SIGNAL = re.compile(r"\bmu\b|μ|signal[\s-]+strength", re.IGNORECASE)
_ASYM = re.compile(
    r"""(?x)
    \s*\+\s*
    (?P<up>\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)
    \s*/?\s*
    [-−]\s*
    (?P<down>\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)
    """
)
_UNIT = re.compile(
    r"""(?ix)
    [ \t]{0,4}
    (?:
        \\(?:mathrm|rm|text)\{
            (?P<latex>TeV|GeV|MeV|keV|eV|ab|fb|pb|nb|ub|mb)
        \}
        (?P<latexinv>\s*\^\s*\{?\s*-\s*1\s*\}?)?
      |
        (?P<sym>TeV|GeV|MeV|keV|eV|ab|fb|pb|nb|ub|mb)
        (?P<inv>\s*\^\s*\{?\s*-\s*1\s*\}?|⁻¹|-1)?
      |
        %
    )
    (?![A-Za-z0-9])
    """
)

# Longest phrase first so "inverse femtobarns" wins over "femtobarns".
_SPOKEN_UNITS: tuple[tuple[str, str], ...] = (
    ("inverse femtobarns", "fb-1"),
    ("inverse femtobarn", "fb-1"),
    ("inverse picobarns", "pb-1"),
    ("inverse picobarn", "pb-1"),
    ("inverse nanobarns", "nb-1"),
    ("inverse nanobarn", "nb-1"),
    ("inverse attobarns", "ab-1"),
    ("inverse attobarn", "ab-1"),
    ("teraelectronvolts", "TeV"),
    ("teraelectronvolt", "TeV"),
    ("gigaelectronvolts", "GeV"),
    ("gigaelectronvolt", "GeV"),
    ("megaelectronvolts", "MeV"),
    ("megaelectronvolt", "MeV"),
    ("kiloelectronvolts", "keV"),
    ("kiloelectronvolt", "keV"),
    ("electronvolts", "eV"),
    ("electronvolt", "eV"),
    ("femtobarns", "fb"),
    ("femtobarn", "fb"),
    ("picobarns", "pb"),
    ("picobarn", "pb"),
    ("nanobarns", "nb"),
    ("nanobarn", "nb"),
    ("microbarns", "ub"),
    ("microbarn", "ub"),
    ("millibarns", "mb"),
    ("millibarn", "mb"),
    ("per cent", "%"),
    ("percent", "%"),
)

_SCI_TAIL = re.compile(
    r"""(?ix)
    \s*(?:times|×)\s+ten\s+to\s+the\s+
    (?:(?P<sign>minus|negative|[-−])\s+)?
    (?P<exp>[A-Za-z]+(?:-[A-Za-z]+)?|\d+)
    """
)


@dataclass(frozen=True)
class UnitInfo:
    """A unit reduced to a family so TeV and GeV can be compared."""

    family: str
    canonical: str
    to_canonical: Decimal


UNITS: dict[str, UnitInfo] = {
    "eV": UnitInfo("energy", "GeV", Decimal("1e-9")),
    "keV": UnitInfo("energy", "GeV", Decimal("1e-6")),
    "MeV": UnitInfo("energy", "GeV", Decimal("0.001")),
    "GeV": UnitInfo("energy", "GeV", Decimal(1)),
    "TeV": UnitInfo("energy", "GeV", Decimal(1000)),
    "fb-1": UnitInfo("lumi", "fb-1", Decimal(1)),
    "pb-1": UnitInfo("lumi", "fb-1", Decimal("0.001")),
    "nb-1": UnitInfo("lumi", "fb-1", Decimal("1e-6")),
    "ub-1": UnitInfo("lumi", "fb-1", Decimal("1e-9")),
    "ab-1": UnitInfo("lumi", "fb-1", Decimal(1000)),
    "fb": UnitInfo("xsec", "pb", Decimal("0.001")),
    "pb": UnitInfo("xsec", "pb", Decimal(1)),
    "nb": UnitInfo("xsec", "pb", Decimal(1000)),
    "ub": UnitInfo("xsec", "pb", Decimal(1_000_000)),
    "mb": UnitInfo("xsec", "pb", Decimal("1e9")),
    "%": UnitInfo("percent", "%", Decimal(1)),
    "fraction": UnitInfo("percent", "%", Decimal(100)),
}


@dataclass
class NumberHit:
    value: Decimal
    quantum: Decimal
    unit: str | None
    uncertainty: Decimal | None
    uncertainty_quantum: Decimal | None
    uncertainty_up: Decimal | None
    uncertainty_down: Decimal | None
    uncertainty_up_quantum: Decimal | None
    uncertainty_down_quantum: Decimal | None
    start: int
    end: int
    surface: str
    path: str
    line: int
    kind: str
    hints: frozenset[str]
    # Context for the claim, filled from nearby words. ``component`` is
    # central / stat / syst / total. ``kind`` stays the document role
    # (slide or narration).
    process: str | None = None
    component: str | None = None
    quantity: str | None = None
    calls_signal: bool = False
    calls_cross_section: bool = False


def extract_numbers(document: Document) -> list[NumberHit]:
    """Return every claim-like number in ``document``, in order."""
    text = document.text.replace("\u00a0", " ").replace("\u2212", "-")
    hits: list[NumberHit] = []
    index = 0
    while index < len(text):
        if not _boundary(text, index):
            index += 1
            continue
        bundle = _try_labelled_bundle(text, index)
        if bundle is not None:
            pieces, end = bundle
            for start, parsed in pieces:
                hits.append(_hit_from(document, text, start, parsed))
            index = end
            continue
        parsed = _try_version(text, index) or _try_value(text, index)
        if parsed is None:
            index += 1
            continue
        hits.append(_hit_from(document, text, index, parsed))
        index = parsed.end
    _annotate_context(text, hits)
    return hits


def _hit_from(document: Document, text: str, start: int, parsed: _Parsed) -> NumberHit:
    hints, line = _locate(document, start)
    return NumberHit(
        value=parsed.value,
        quantum=parsed.quantum,
        unit=parsed.unit,
        uncertainty=parsed.uncertainty,
        uncertainty_quantum=parsed.uncertainty_quantum,
        uncertainty_up=parsed.uncertainty_up,
        uncertainty_down=parsed.uncertainty_down,
        uncertainty_up_quantum=parsed.uncertainty_up_quantum,
        uncertainty_down_quantum=parsed.uncertainty_down_quantum,
        start=start,
        end=parsed.end,
        surface=text[start : parsed.end],
        path=document.path,
        line=line,
        kind=document.kind,
        hints=frozenset(set(hints) | set(parsed.hints)),
        component=parsed.component,
    )


def _try_labelled_bundle(
    text: str, index: int
) -> tuple[list[tuple[int, _Parsed]], int] | None:
    """Split ``1.31 ± 0.24 (stat) ± 0.26 (syst)`` into one hit per piece.

    A plain ``±`` with no stat/syst/total label stays with the generic
    parser so an unlabelled symmetric uncertainty is still one claim.
    """
    match = _NUM.match(text, index)
    if match is None or match.group("exp") or match.group("sign") in {"-", "−"}:
        return None
    if match.end() < len(text) and text[match.end()].isalpha():
        return None
    pieces: list[re.Match[str]] = []
    cursor = match.end()
    while True:
        piece = _LABELLED_PIECE.match(text, cursor)
        if piece is None:
            break
        pieces.append(piece)
        cursor = piece.end()
    if not pieces or not any(piece.group("label") for piece in pieces):
        return None
    sign = match.group("sign") or ""
    value, quantum = _compose(sign, match.group("body"), match.group("frac"), None)
    built: list[tuple[int, _Parsed]] = [
        (
            index,
            _Parsed(value=value, quantum=quantum, end=match.end(), component="central"),
        )
    ]
    for piece in pieces:
        label = piece.group("label")
        component = _component_name(label) if label else None
        number = piece.group("num")
        if "." in number:
            whole, frac = number.split(".", 1)
            piece_value, piece_quantum = _compose("", whole, frac, None)
        else:
            piece_value, piece_quantum = _compose("", number, None, None)
        number_start = piece.start("num")
        built.append(
            (
                number_start,
                _Parsed(
                    value=piece_value,
                    quantum=piece_quantum,
                    end=piece.end("num"),
                    component=component,
                ),
            )
        )
    return built, cursor


def _component_name(label: str) -> str:
    lowered = label.lower()
    if lowered.startswith("stat"):
        return "stat"
    if lowered.startswith("syst"):
        return "syst"
    return "total"


def _annotate_context(text: str, hits: list[NumberHit]) -> None:
    for hit in hits:
        before = text[max(0, hit.start - 80) : hit.start]
        processes = list(_PROCESS.finditer(before))
        if processes:
            hit.process = processes[-1].group(1).upper()
        sentence = _sentence_around(text, hit.start)
        hit.calls_cross_section = _CROSS_SECTION.search(sentence) is not None
        hit.calls_signal = _SIGNAL.search(sentence) is not None
        if hit.calls_cross_section:
            hit.quantity = "cross_section"
        elif hit.calls_signal:
            hit.quantity = "mu"


def _sentence_around(text: str, index: int) -> str:
    start = max(text.rfind("\n", 0, index), text.rfind(".", 0, index))
    end_break = text.find("\n", index)
    end_stop = text.find(".", index)
    candidates = [pos for pos in (end_break, end_stop) if pos != -1]
    end = min(candidates) if candidates else len(text)
    return text[start + 1 : end]


@dataclass
class _Parsed:
    value: Decimal
    quantum: Decimal
    end: int
    component: str | None = None
    unit: str | None = None
    uncertainty: Decimal | None = None
    uncertainty_quantum: Decimal | None = None
    uncertainty_up: Decimal | None = None
    uncertainty_down: Decimal | None = None
    uncertainty_up_quantum: Decimal | None = None
    uncertainty_down_quantum: Decimal | None = None
    hints: frozenset[str] = frozenset()
    start: int = 0


def _boundary(text: str, index: int) -> bool:
    if index == 0:
        return True
    previous = text[index - 1]
    return not (previous.isalnum() or previous == "_")


def _locate(document: Document, index: int) -> tuple[frozenset[str], int]:
    hints: set[str] = set()
    line = document.text.count("\n", 0, index) + 1
    for region in document.regions:
        if region.start <= index < region.end:
            hints.update(region.hints)
            line = region.line
            break
    return frozenset(hints), line


def _try_version(text: str, index: int) -> _Parsed | None:
    match = _VERSION.match(text, index)
    if match is None:
        return None
    if match.end() < len(text) and text[match.end()].isalpha():
        return None
    return _Parsed(
        value=Decimal(match.group(0).split(".", 1)[0]),
        quantum=Decimal(1),
        end=match.end(),
        hints=frozenset({"version"}),
    )


def _try_value(text: str, index: int) -> _Parsed | None:
    spoken = _try_spoken(text, index)
    numeric = _try_numeric(text, index)
    if spoken is None:
        return numeric
    if numeric is None:
        return spoken
    # Prefer whichever consumes more of the text. They rarely both fire.
    if spoken.end >= numeric.end:
        return spoken
    return numeric


def _try_numeric(text: str, index: int) -> _Parsed | None:
    match = _TIMES.match(text, index) or _NUM.match(text, index)
    if match is None:
        return None
    if match.end() < len(text) and text[match.end()].isalpha():
        return None
    if _NUM.match(text, index) and _TIMES.match(text, index) is None:
        # "1.2.3" is a version, already handled. "1.2." with a trailing dot
        # and another number is not a single decimal.
        after = match.end()
        if after < len(text) and text[after] == "." and after + 1 < len(text) and text[after + 1].isdigit():
            return None
    sign = match.group("sign") or ""
    if "whole" in match.groupdict() and match.group("whole") is not None:
        whole = match.group("whole")
    else:
        whole = match.group("body")
    frac = match.group("frac")
    exp = match.group("exp")
    if sign in {"-", "−"} and index > 0 and text[index - 1].isdigit():
        return None
    value, quantum = _compose(sign, whole, frac, exp)
    end = match.end()
    if not exp:
        tail = _SCI_TAIL.match(text, end)
        if tail is not None:
            exponent = _small_integer(tail.group("exp") or "")
            if exponent is not None:
                if tail.group("sign"):
                    exponent = -exponent
                places = len(frac) if frac else 0
                value, quantum = _compose(sign, whole, frac, str(exponent))
                end = tail.end()
    return _attach(text, end, value, quantum, strong=True)


def _try_spoken(text: str, index: int) -> _Parsed | None:
    words = _read_spoken_words(text, index)
    if not words:
        return None
    tokens = [match.group().lower() for match in words]
    if "point" in tokens:
        point_at = tokens.index("point")
        integer_tokens = tokens[:point_at]
        frac_tokens = tokens[point_at + 1 :]
        if not frac_tokens or any(token not in _ONES or token == "a" for token in frac_tokens):
            return None
        integer = 0 if not integer_tokens else _eval_integer(integer_tokens)
        if integer is None:
            return None
        frac_digits = "".join(str(_ONES[token]) for token in frac_tokens)
        end = words[point_at + len(frac_tokens)].end()
        strong = True
    else:
        integer = _eval_integer(tokens)
        if integer is None:
            return None
        frac_digits = ""
        end = words[len(tokens) - 1].end()
        strong = _spoken_is_strong(tokens)
    sign = ""
    value, quantum = _compose(sign, str(integer), frac_digits or None, None)
    tail = _SCI_TAIL.match(text, end)
    if tail is not None:
        exponent = _small_integer(tail.group("exp"))
        if exponent is None:
            return None
        if tail.group("sign"):
            exponent = -exponent
        places = len(frac_digits)
        value = value.scaleb(exponent)
        quantum = Decimal(10) ** (exponent - places)
        end = tail.end()
        strong = True
    parsed = _attach(text, end, value, quantum, strong=strong)
    if parsed is None:
        return None
    return parsed


def _spoken_is_strong(tokens: list[str]) -> bool:
    if any("-" in token for token in tokens):
        return True
    if any(token in _SCALES for token in tokens):
        return True
    if len([token for token in tokens if token != "and"]) > 1:
        return True
    return False


def _read_spoken_words(text: str, index: int) -> list[re.Match[str]]:
    match = _WORD.match(text, index)
    if match is None or not _could_start_number(match.group().lower()):
        return []
    words = [match]
    while True:
        cursor = words[-1].end()
        spacer = cursor
        while spacer < len(text) and text[spacer] in " \t":
            spacer += 1
        if spacer == cursor:
            break
        nxt = _WORD.match(text, spacer)
        if nxt is None:
            break
        token = nxt.group().lower()
        if not _could_continue(token, [item.group().lower() for item in words]):
            break
        words.append(nxt)
    # Drop a trailing "and" or "point" that never got a number after it.
    while words and words[-1].group().lower() in {"and", "point"}:
        words.pop()
    if not words:
        return []
    return words


def _could_start_number(token: str) -> bool:
    if token in {"point", "and", "hundred"}:
        return False
    return _is_number_word(token) or token == "a"


def _could_continue(token: str, previous: list[str]) -> bool:
    if token == "and":
        return "point" not in previous
    if token == "point":
        return "point" not in previous
    if "point" in previous:
        return token in _ONES and token != "a"
    return _is_number_word(token)


def _is_number_word(token: str) -> bool:
    if token in _ONES or token in _TEENS or token in _TENS or token in _SCALES:
        return True
    if "-" in token:
        left, right = token.split("-", 1)
        return left in _TENS and right in _ONES and right != "a"
    return False


def _eval_integer(tokens: list[str]) -> int | None:
    total = 0
    current = 0
    seen = False
    for token in tokens:
        if token == "and":
            if not seen:
                return None
            continue
        if "-" in token:
            left, right = token.split("-", 1)
            if left not in _TENS or right not in _ONES or right == "a":
                return None
            current += _TENS[left] + _ONES[right]
            seen = True
            continue
        if token in _TENS:
            current += _TENS[token]
            seen = True
            continue
        if token in _TEENS:
            current += _TEENS[token]
            seen = True
            continue
        if token in _ONES and token != "a":
            current += _ONES[token]
            seen = True
            continue
        if token == "a":
            current += 1
            seen = True
            continue
        if token == "hundred":
            if current == 0:
                current = 1
            current *= 100
            seen = True
            continue
        if token in {"thousand", "million", "billion"}:
            if current == 0:
                current = 1
            total += current * _SCALES[token]
            current = 0
            seen = True
            continue
        return None
    if not seen:
        return None
    return total + current


def _small_integer(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    values = _eval_integer([token.lower()])
    if values is None or values > 99:
        return None
    return values


def _compose(
    sign: str, whole: str, frac: str | None, exp: str | None
) -> tuple[Decimal, Decimal]:
    digits = whole.replace(",", "")
    places = len(frac) if frac else 0
    mantissa = Decimal(f"{digits}.{frac}") if frac else Decimal(digits)
    if sign in {"-", "−"}:
        mantissa = -mantissa
    exponent = int(exp.replace("−", "-")) if exp else 0
    return mantissa.scaleb(exponent), Decimal(10) ** (exponent - places)


def _attach(
    text: str, end: int, value: Decimal, quantum: Decimal, *, strong: bool
) -> _Parsed | None:
    """Pull an optional uncertainty and unit off the tail of a magnitude.

    Both orders are accepted: ``1.2 ± 0.1 GeV`` and ``1.2 GeV ± 0.1``.
    """
    uncertainty = _try_uncertainty(text, end)
    if uncertainty is None:
        unit = _try_unit(text, end)
        if unit is not None:
            uncertainty = _try_uncertainty(text, unit[1])
            final = uncertainty.end if uncertainty is not None else unit[1]
        else:
            final = end
    else:
        unit = _try_unit(text, uncertainty.end)
        final = unit[1] if unit is not None else uncertainty.end
    if not strong and uncertainty is None and unit is None:
        return None
    parsed = _Parsed(
        value=value,
        quantum=quantum,
        end=final,
        unit=None if unit is None else unit[0],
    )
    if uncertainty is not None:
        parsed.uncertainty = uncertainty.symmetric
        parsed.uncertainty_quantum = uncertainty.symmetric_quantum
        parsed.uncertainty_up = uncertainty.up
        parsed.uncertainty_down = uncertainty.down
        parsed.uncertainty_up_quantum = uncertainty.up_quantum
        parsed.uncertainty_down_quantum = uncertainty.down_quantum
    return parsed


@dataclass
class _Unc:
    end: int
    symmetric: Decimal | None = None
    symmetric_quantum: Decimal | None = None
    up: Decimal | None = None
    down: Decimal | None = None
    up_quantum: Decimal | None = None
    down_quantum: Decimal | None = None


def _try_uncertainty(text: str, index: int) -> _Unc | None:
    plus_minus = _PM.match(text, index)
    if plus_minus is not None:
        number = _bare_number(text, plus_minus.end())
        if number is None:
            return None
        value, quantum, end = number
        return _Unc(end=end, symmetric=value, symmetric_quantum=quantum)
    asymmetric = _ASYM.match(text, index)
    if asymmetric is not None:
        up, up_q = _parse_decimal_token(asymmetric.group("up"))
        down, down_q = _parse_decimal_token(asymmetric.group("down"))
        return _Unc(
            end=asymmetric.end(),
            up=up,
            down=down,
            up_quantum=up_q,
            down_quantum=down_q,
        )
    return None


def _parse_decimal_token(token: str) -> tuple[Decimal, Decimal]:
    match = _NUM.fullmatch(token)
    if match is None:
        return Decimal(token), Decimal(1)
    return _compose(
        match.group("sign") or "",
        match.group("body"),
        match.group("frac"),
        match.group("exp"),
    )


def _bare_number(text: str, index: int) -> tuple[Decimal, Decimal, int] | None:
    """A numeric or spoken magnitude with no unit and no nested uncertainty."""
    if index < len(text) and text[index] in " \t":
        while index < len(text) and text[index] in " \t":
            index += 1
    match = _NUM.match(text, index)
    if match is not None and match.group("exp") is None and not (
        match.end() < len(text) and text[match.end()].isalpha()
    ):
        sign = match.group("sign") or ""
        value, quantum = _compose(sign, match.group("body"), match.group("frac"), None)
        return value, quantum, match.end()
    words = _read_spoken_words(text, index)
    if not words:
        return None
    tokens = [item.group().lower() for item in words]
    if "point" in tokens:
        point_at = tokens.index("point")
        frac_tokens = tokens[point_at + 1 :]
        if not frac_tokens or any(token not in _ONES or token == "a" for token in frac_tokens):
            return None
        integer_tokens = tokens[:point_at]
        integer = 0 if not integer_tokens else _eval_integer(integer_tokens)
        if integer is None:
            return None
        frac = "".join(str(_ONES[token]) for token in frac_tokens)
        value, quantum = _compose("", str(integer), frac, None)
        return value, quantum, words[-1].end()
    integer = _eval_integer(tokens)
    if integer is None:
        return None
    value, quantum = _compose("", str(integer), None, None)
    return value, quantum, words[-1].end()


def _try_unit(text: str, index: int) -> tuple[str, int] | None:
    cursor = index
    while cursor < len(text) and text[cursor] in " \t":
        cursor += 1
    if cursor >= len(text):
        return None
    lowered_tail = text[cursor:].lower()
    for phrase, canonical in _SPOKEN_UNITS:
        if lowered_tail.startswith(phrase):
            end = cursor + len(phrase)
            if end < len(text) and text[end].isalpha():
                continue
            return canonical, end
    match = _UNIT.match(text, index)
    if match is None:
        return None
    if match.group(0).strip() == "%":
        return "%", match.end()
    symbol = match.group("sym") or match.group("latex")
    if symbol is None:
        return "%", match.end()
    inverse = bool(match.group("inv") or match.group("latexinv"))
    canonical = _canonical_symbol(symbol, inverse)
    return canonical, match.end()


def _canonical_symbol(symbol: str, inverse: bool) -> str:
    table = {
        "tev": "TeV",
        "gev": "GeV",
        "mev": "MeV",
        "kev": "keV",
        "ev": "eV",
        "fb": "fb",
        "pb": "pb",
        "nb": "nb",
        "ub": "ub",
        "mb": "mb",
        "ab": "ab",
    }
    base = table[symbol.lower()]
    if base in {"TeV", "GeV", "MeV", "keV", "eV"}:
        return base
    if inverse:
        return f"{base}-1"
    return base


def canonical_unit(text: str) -> str | None:
    """Map a manifest unit string onto a canonical unit id, or None."""
    parsed = _try_unit(f" {text.strip()}", 0)
    if parsed is None:
        return None
    _, end = parsed
    if text.strip() == "":
        return None
    # The parser may ignore trailing junk. Require it to consume the token.
    consumed = parsed[1]
    probe = " " + text.strip()
    if consumed < len(probe) and probe[consumed:].strip():
        return None
    return parsed[0]


def convert(value: Decimal, from_unit: str | None, to_unit: str | None) -> Decimal | None:
    """Express ``value`` in ``to_unit``. None when the families differ."""
    if from_unit is None or to_unit is None or from_unit == to_unit:
        return value
    source = UNITS.get(from_unit)
    target = UNITS.get(to_unit)
    if source is None or target is None:
        return None
    if source.family != target.family:
        return None
    return value * source.to_canonical / target.to_canonical


def quantum_of(value: Decimal) -> Decimal:
    """Last-digit quantum of a ``Decimal`` that was parsed from text."""
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent >= 0:
        return Decimal(1)
    return Decimal(10) ** exponent
