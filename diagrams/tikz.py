"""TikZ-Feynman source for a resolved diagram.

Edges run along the momentum, from ``source`` to ``target``. A fermion
uses ``fermion`` when the arrow is with the momentum and ``anti fermion``
when it is against the momentum, which is the TikZ-Feynman way to reverse
the arrowhead.
"""

from __future__ import annotations

from checks.ufo_model import load_model

from diagrams.labels import latex_label


def tikz_source(drawing: dict) -> str:
    model = load_model()
    positions = drawing.get("positions") or {}
    lines = []
    lines.append(r"\documentclass[tikz,border=10pt]{standalone}")
    lines.append(r"\usepackage{amsmath,amssymb,physics,siunitx}")
    lines.append(r"\usepackage[compat=1.1.0]{tikz-feynman}")
    lines.append(r"\begin{document}")
    lines.append(r"\begin{tikzpicture}")
    lines.append(r"\begin{feynman}")
    labelled = _external_labels(drawing)
    for name, coords in positions.items():
        x, y = float(coords[0]), float(coords[1])
        label = labelled.get(str(name))
        if label:
            lines.append(rf"  \vertex ({name}) at ({x:.3f},{y:.3f}) {{\({label}\)}};")
        else:
            lines.append(rf"  \vertex ({name}) at ({x:.3f},{y:.3f});")
    degree = _degree(drawing)
    edges = []
    for line in drawing["lines"]:
        style = _style(line, model)
        source = str(line["source"])
        target = str(line["target"])
        label = ""
        if degree.get(source, 0) > 1 and degree.get(target, 0) > 1:
            label = ", edge label={" + r"\(" + latex_label(line["particle"]) + r"\)" + "}"
        edges.append(f"    ({source}) -- [{style}{label}] ({target}),")
    lines.append(r"  \diagram* {")
    lines.extend(edges)
    lines.append(r"  };")
    lines.append(r"\end{feynman}")
    lines.append(r"\end{tikzpicture}")
    lines.append(r"\end{document}")
    return "\n".join(lines) + "\n"


def _degree(drawing: dict) -> dict[str, int]:
    degree = {str(name): 0 for name in (drawing.get("positions") or {})}
    for line in drawing["lines"]:
        for end in (str(line["source"]), str(line["target"])):
            degree[end] = degree.get(end, 0) + 1
    return degree


def _external_labels(drawing: dict) -> dict[str, str]:
    """Label a coordinate that is the outer end of exactly one line."""
    degree = _degree(drawing)
    labels: dict[str, str] = {}
    for line in drawing["lines"]:
        for end in (str(line["source"]), str(line["target"])):
            if degree.get(end) == 1:
                labels[end] = latex_label(line["particle"])
    return labels


def _style(line: dict, model) -> str:
    parsed = model.parse(line["particle"])
    if parsed.fermion:
        if line["arrow"] == "with_momentum":
            return "fermion"
        if line["arrow"] == "against_momentum":
            return "anti fermion"
        return "plain"
    choice = parsed.options[0]
    if choice.pdg in {22, -22} or choice.name.lower() in {"a", "gamma"}:
        return "photon"
    if choice.name.lower() in {"g"} or choice.pdg == 21:
        return "gluon"
    if choice.spin == 1:
        return "scalar"
    return "boson"
