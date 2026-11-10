"""Load the vendored Standard Model UFO and answer vertex queries.

The particle and vertex lists come from ``checks/models/sm-ufo``, the
FeynRules SM UFO as shipped in MadGraph5_aMC@NLO. See
``checks/models/PROVENANCE.md``. Digests are checked before the files
are executed. Nothing in this module is a hand-written vertex table.
"""

from __future__ import annotations

import hashlib
import importlib
import sys
from dataclasses import dataclass
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parent / "models" / "sm-ufo"
_SUMS = MODEL_DIR / "SHA256SUMS"
_CHARGE_EPS = 1e-6

# Import order inside the UFO. ``vertices`` pulls the rest.
_LOAD_NAMES = (
    "object_library",
    "function_library",
    "parameters",
    "particles",
    "coupling_orders",
    "couplings",
    "lorentz",
    "vertices",
)


class ModelError(RuntimeError):
    """The vendored UFO is missing or does not match its pin."""


@dataclass(frozen=True)
class Choice:
    """One concrete external state a diagram label can stand for."""

    pdg: int
    charge: float
    lepton: float
    spin: int
    name: str
    self_conjugate: bool = False

    @property
    def flavour(self) -> int:
        return abs(self.pdg)


@dataclass(frozen=True)
class Parsed:
    raw: str
    canonical: str
    prime: int
    family: str | None
    options: tuple[Choice, ...]

    @property
    def fermion(self) -> bool:
        return bool(self.options) and all(item.spin == 2 for item in self.options)


@dataclass(frozen=True)
class VertexVerdict:
    ok: bool
    message: str
    vertex: str = ""


@dataclass
class Model:
    signatures: dict[tuple[int, ...], str]
    by_name: dict[str, Choice]
    families: dict[str, tuple[Choice, ...]]

    def parse(self, token: str) -> Parsed:
        return _parse(token, self)

    def allows(self, legs: list[str]) -> VertexVerdict:
        return _allows(self, legs)


_MODEL: Model | None = None


def load_model() -> Model:
    """Return the cached SM UFO. Verifies SHA256SUMS on first load."""
    global _MODEL
    if _MODEL is None:
        _verify_pin()
        _MODEL = _execute()
    return _MODEL


def _verify_pin() -> None:
    if not _SUMS.is_file():
        raise ModelError(f"missing pin file {_SUMS}")
    listed: list[tuple[str, Path]] = []
    for line in _SUMS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, _, name = line.partition(" ")
        name = name.strip()
        if not digest or not name:
            raise ModelError(f"bad SHA256SUMS line: {line}")
        path = (MODEL_DIR / name).resolve()
        if MODEL_DIR.resolve() not in path.parents and path != MODEL_DIR.resolve():
            raise ModelError(f"pin path escapes the model directory: {name}")
        if not path.is_file():
            raise ModelError(f"pinned file missing: {name}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest.lower():
            raise ModelError(
                f"UFO digest mismatch for {name}: {actual} != {digest.lower()}"
            )
        listed.append((digest, path))
    if len(listed) < 5:
        raise ModelError("SHA256SUMS does not cover the UFO")


def _execute() -> Model:
    saved_path = list(sys.path)
    saved_modules = {name: sys.modules.get(name) for name in _LOAD_NAMES}
    for name in _LOAD_NAMES:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(MODEL_DIR))
    try:
        importlib.invalidate_caches()
        vertices = importlib.import_module("vertices")
        object_library = sys.modules["object_library"]
        particles = list(object_library.all_particles)
        vertex_list = list(object_library.all_vertices)
        # Touch the module so a partial import still fails loudly.
        if not hasattr(vertices, "all_vertices") and not vertex_list:
            raise ModelError("UFO vertices.py did not define vertices")
    finally:
        sys.path = saved_path
        for name in _LOAD_NAMES:
            sys.modules.pop(name, None)
        for name, module in saved_modules.items():
            if module is not None:
                sys.modules[name] = module
    if not particles or not vertex_list:
        raise ModelError("UFO import produced no particles or vertices")
    return _build(particles, vertex_list)


def _lepton(particle: object) -> float:
    value = getattr(particle, "LeptonNumber", 0)
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _choice_from(particle: object) -> Choice:
    return Choice(
        pdg=int(particle.pdg_code),
        charge=float(particle.charge),
        lepton=_lepton(particle),
        spin=int(particle.spin),
        name=str(particle.name),
        self_conjugate=bool(getattr(particle, "selfconjugate", False)),
    )


def _flipped(choice: Choice) -> Choice | None:
    if choice.self_conjugate:
        return None
    return Choice(
        pdg=-choice.pdg,
        charge=-choice.charge,
        lepton=-choice.lepton,
        spin=choice.spin,
        name=choice.name + "~",
        self_conjugate=False,
    )


def _build(particles: list[object], vertex_list: list[object]) -> Model:
    by_name: dict[str, Choice] = {}
    positive: list[Choice] = []
    self_conjugate: set[int] = set()
    for particle in particles:
        choice = _choice_from(particle)
        by_name[choice.name.lower()] = choice
        if bool(getattr(particle, "selfconjugate", False)):
            self_conjugate.add(choice.pdg)
        if choice.pdg > 0:
            positive.append(choice)

    signatures: dict[tuple[int, ...], str] = {}
    for vertex in vertex_list:
        pdgs = tuple(sorted(int(particle.pdg_code) for particle in vertex.particles))
        conjugate = tuple(
            sorted(_conjugate_pdg(particle, self_conjugate) for particle in vertex.particles)
        )
        name = str(vertex.name)
        signatures.setdefault(pdgs, name)
        signatures.setdefault(conjugate, name)

    quarks = tuple(
        item for item in positive if item.spin == 2 and abs(_color(item, particles)) == 3
    )
    leptons = tuple(item for item in positive if item.spin == 2 and abs(item.lepton) > _CHARGE_EPS)
    charged = tuple(item for item in leptons if abs(item.charge) > _CHARGE_EPS)
    neutrinos = tuple(item for item in leptons if abs(item.charge) <= _CHARGE_EPS)
    families = {"q": quarks, "l": charged, "nu": neutrinos}
    for key, group in families.items():
        if not group:
            raise ModelError(f"SM UFO has no particles for the {key} family")
    return Model(signatures=signatures, by_name=by_name, families=families)


def _color(choice: Choice, particles: list[object]) -> int:
    for particle in particles:
        if int(particle.pdg_code) == choice.pdg:
            return int(particle.color)
    return 0


def _conjugate_pdg(particle: object, self_conjugate: set[int]) -> int:
    pdg = int(particle.pdg_code)
    if pdg in self_conjugate or bool(getattr(particle, "selfconjugate", False)):
        return pdg
    return -pdg


_PRIMES = "'′"
_BARS = ("bar", "~")


def split_token(raw: str) -> tuple[str, int, bool]:
    """Return ``(stem, prime_count, is_anti)`` for a diagram label.

    ``qbar'``, ``q'bar``, ``q~``, and ``b*`` are accepted. A trailing ``*``
    marks an off-shell line and is dropped. The stem keeps charge signs,
    so ``W+`` and ``e-`` stay intact.
    """
    text = str(raw).strip().replace("−", "-").replace("–", "-")
    text = text.replace("\u0304", "bar")
    if text.endswith("*"):
        text = text[:-1]
    primes = 0
    is_anti = False
    while text:
        if text[-1] in _PRIMES:
            primes += 1
            text = text[:-1]
            continue
        lowered = text.lower()
        if lowered.endswith("bar"):
            if is_anti:
                break
            is_anti = True
            text = text[:-3]
            continue
        if text.endswith("~"):
            if is_anti:
                break
            is_anti = True
            text = text[:-1]
            continue
        break
    if not text:
        raise ModelError(f"empty particle label {raw!r}")
    return text, primes, is_anti


# Notation only. These names are not vertices. They point a printed label
# at the UFO particle of the same state (or at a family handled below).
_STEM_ALIAS = {
    "gamma": "a",
    "photon": "a",
    "γ": "a",
    "gluon": "g",
    "higgs": "h",
    "h": "h",
    "e": "e-",
    "electron": "e-",
    "positron": "e+",
    "mu": "mu-",
    "muon": "mu-",
    "tau": "ta-",
    "ta": "ta-",
    "nue": "ve",
    "nu_e": "ve",
    "νe": "ve",
    "numu": "vm",
    "nu_mu": "vm",
    "νμ": "vm",
    "nutau": "vt",
    "nu_tau": "vt",
    "ντ": "vt",
}


def canonical_token(raw: str) -> str:
    """Label identity used to compare a diagram with an excerpt.

    Off-shell stars are ignored. ``b~`` and ``bbar`` match. ``H`` and ``h``
    match. ``gamma`` and ``a`` match. Primes are kept, so ``qbar`` and
    ``qbar'`` do not match.
    """
    stem, primes, is_anti = split_token(raw)
    stem_l = _STEM_ALIAS.get(stem.lower(), stem.lower())
    if is_anti and stem_l.endswith("-"):
        stem_l = stem_l[:-1] + "+"
        is_anti = False
    elif is_anti and stem_l.endswith("+"):
        stem_l = stem_l[:-1] + "-"
        is_anti = False
    body = stem_l
    if is_anti:
        body += "bar"
    body += "'" * primes
    return body


def _parse(token: str, model: Model) -> Parsed:
    stem, primes, is_anti = split_token(token)
    canonical = canonical_token(token)
    stem_l = stem.lower()
    if stem_l in {"q", "l", "nu"}:
        bases = model.families[stem_l]
        options = []
        for base in bases:
            choice = _apply_bar(base, is_anti)
            if choice is not None:
                options.append(choice)
        if not options:
            raise ModelError(f"{token!r} has no antiparticle in the SM UFO")
        return Parsed(token, canonical, primes, stem_l, tuple(options))
    if stem_l == "w" and primes == 0:
        plus = model.by_name.get("w+")
        minus = model.by_name.get("w-")
        if plus is None or minus is None:
            raise ModelError("SM UFO has no W+ / W-")
        # ``W`` is the charge multiplet. Each leg chooses W+ or W- on its own.
        return Parsed(token, canonical, primes, None, (plus, minus))
    looked = _STEM_ALIAS.get(stem_l, stem_l)
    found = model.by_name.get(looked)
    if found is None:
        raise ModelError(f"unknown particle {token!r}")
    choice = _apply_bar(found, is_anti)
    if choice is None:
        raise ModelError(f"{token!r} is self-conjugate in the SM UFO and has no bar")
    return Parsed(token, canonical, primes, None, (choice,))


def _apply_bar(choice: Choice, is_anti: bool) -> Choice | None:
    if not is_anti:
        return choice
    flipped = _flipped(choice)
    return flipped


def _allows(model: Model, legs: list[str]) -> VertexVerdict:
    if not legs:
        return VertexVerdict(False, "vertex has no legs")
    try:
        parsed = [model.parse(leg) for leg in legs]
    except ModelError as exc:
        return VertexVerdict(False, str(exc))
    groups: dict[tuple[str, int], list[int]] = {}
    for index, label in enumerate(parsed):
        if label.family is None:
            continue
        groups.setdefault((label.family, label.prime), []).append(index)
    domains: list[tuple[tuple[str, int], list[int]]] = []
    for key, members in groups.items():
        allowed: set[int] | None = None
        for member in members:
            flavours = {choice.flavour for choice in parsed[member].options}
            allowed = flavours if allowed is None else allowed & flavours
        if not allowed:
            return VertexVerdict(
                False,
                f"{_shown(parsed)}: family labels have no common flavour",
            )
        domains.append((key, sorted(allowed)))
    charge_misses = 0
    vertex_misses = 0
    example = ""
    tried = 0
    for assignment in _product(domains):
        chosen = dict(assignment)
        # Different primes of one family are different flavours.
        by_family: dict[str, list[int]] = {}
        clash = False
        for (family, _prime), pdg in chosen.items():
            by_family.setdefault(family, []).append(pdg)
        for flavours in by_family.values():
            if len(flavours) != len(set(flavours)):
                clash = True
        if clash:
            continue
        leg_options: list[list[Choice]] = []
        impossible = False
        for index, label in enumerate(parsed):
            if label.family is None:
                leg_options.append(list(label.options))
                continue
            pdg = chosen[(label.family, label.prime)]
            matched = [choice for choice in label.options if choice.flavour == pdg]
            if not matched:
                impossible = True
                break
            leg_options.append(matched)
        if impossible:
            continue
        for combo in _product_choices(leg_options):
            tried += 1
            charge = sum(choice.charge for choice in combo)
            names = [choice.name for choice in combo]
            signature = tuple(sorted(choice.pdg for choice in combo))
            if abs(charge) > _CHARGE_EPS:
                charge_misses += 1
                if not example:
                    example = ", ".join(names)
                continue
            hit = model.signatures.get(signature)
            if hit:
                return VertexVerdict(
                    True,
                    f"{_shown(parsed)} matches {hit} ({', '.join(names)})",
                    hit,
                )
            vertex_misses += 1
            if not example:
                example = ", ".join(names)
    shown = _shown(parsed)
    if tried == 0:
        return VertexVerdict(False, f"{shown}: no flavour assignment satisfies the labels")
    if vertex_misses == 0:
        return VertexVerdict(
            False,
            f"{shown}: electric charge is not conserved "
            f"({charge_misses} assignment(s); example {example})",
        )
    return VertexVerdict(
        False,
        f"{shown}: no vertex in the SM UFO has this content "
        f"({vertex_misses} charge-conserving assignment(s) checked; example {example})",
    )


def _shown(parsed: list[Parsed]) -> str:
    return "[" + ", ".join(item.canonical for item in parsed) + "]"


def _product(domains: list[tuple[tuple[str, int], list[int]]]):
    if not domains:
        yield []
        return
    head_key, head_values = domains[0]
    for value in head_values:
        for rest in _product(domains[1:]):
            yield [(head_key, value), *rest]


def _product_choices(options: list[list[Choice]]):
    if not options:
        yield ()
        return
    for choice in options[0]:
        for rest in _product_choices(options[1:]):
            yield (choice, *rest)


def conjugate_token(token: str, model: Model | None = None) -> str:
    """Return the antiparticle label used when crossing an outgoing line.

    UFO vertices use an all-incoming field convention. Diagram files use
    physical momentum directions. A physical outgoing particle therefore
    enters the UFO lookup as its conjugate state. Self-conjugate particles
    and unresolved charge multiplets such as W are unchanged.
    """
    model = model or load_model()
    parsed = model.parse(token)
    if parsed.family is not None:
        stem, primes, is_anti = split_token(token)
        suffix = "'" * primes
        raw = f"{stem}{suffix}" if is_anti else f"{stem}bar{suffix}"
        return canonical_token(raw)
    if len(parsed.options) != 1:
        return parsed.canonical
    choice = parsed.options[0]
    if choice.self_conjugate:
        return parsed.canonical
    wanted = -choice.pdg
    for candidate in model.by_name.values():
        if candidate.pdg == wanted:
            return candidate.name
    flipped = _flipped(choice)
    if flipped is None:
        return parsed.canonical
    return flipped.name

def required_arrow(token: str, model: Model | None = None) -> str | None:
    """Fermion arrow demanded by the label, or None for a boson.

    A fermion's arrow follows fermion number, so it points with the
    momentum. An antifermion's arrow points against the momentum. The
    sign of the PDG code in the UFO is what decides which is which;
    the bar on the label is how an antiparticle is requested.
    """
    model = model or load_model()
    parsed = model.parse(token)
    if not parsed.fermion:
        return None
    if all(choice.pdg < 0 for choice in parsed.options):
        return "against_momentum"
    if all(choice.pdg > 0 for choice in parsed.options):
        return "with_momentum"
    raise ModelError(f"{token!r} mixes fermions and antifermions")
