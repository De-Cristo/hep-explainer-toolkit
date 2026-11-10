"""TeX for a diagram label. The string is the particle, not a vertex rule."""

from __future__ import annotations

from checks.ufo_model import split_token

_SYMBOL = {
    "a": r"\gamma",
    "gamma": r"\gamma",
    "photon": r"\gamma",
    "g": "g",
    "gluon": "g",
    "h": "H",
    "higgs": "H",
    "z": "Z",
    "w": "W",
    "q": "q",
    "u": "u",
    "d": "d",
    "c": "c",
    "s": "s",
    "t": "t",
    "b": "b",
    "e": "e",
    "e-": "e^{-}",
    "e+": "e^{+}",
    "mu-": r"\mu^{-}",
    "mu+": r"\mu^{+}",
    "ta-": r"\tau^{-}",
    "ta+": r"\tau^{+}",
    "nu": r"\nu",
    "ve": r"\nu_{e}",
    "vm": r"\nu_{\mu}",
    "vt": r"\nu_{\tau}",
    "l": r"\ell",
}


def latex_label(token: str) -> str:
    """Return TeX (no math delimiters) for a diagram token."""
    raw = str(token).strip()
    offshell = raw.endswith("*")
    stem, primes, is_anti = split_token(raw)
    key = stem.lower()
    if key in {"w+", "w-"}:
        symbol = "W^{" + key[-1] + "}"
        is_anti = False
    else:
        symbol = _SYMBOL.get(key, stem)
        if is_anti and key.endswith("-"):
            symbol = _SYMBOL.get(key[:-1] + "+", symbol)
            is_anti = False
        elif is_anti and key.endswith("+"):
            symbol = _SYMBOL.get(key[:-1] + "-", symbol)
            is_anti = False
    body = r"\bar{" + symbol + "}" if is_anti else symbol
    body += "'" * primes
    if offshell:
        body += "^{*}"
    return body
