"""Render a diagram file to PNG/SVG, or a short Manim clip."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from checks.diagrams import load_diagram, resolve_drawing
from diagrams.tikz import tikz_source


def render_figure(diagram: Path, png: Path, svg: Path | None = None) -> None:
    drawing = resolve_drawing(load_diagram(diagram))
    render_drawing_figure(drawing, png, svg)


def render_drawing_figure(
    drawing: dict,
    png: Path,
    svg: Path | None = None,
) -> None:
    """Render an already-resolved drawing, including semantic cue subsets."""
    source = tikz_source(drawing)
    png = Path(png).resolve()
    png.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tikz-feynman-") as tmp:
        work = Path(tmp)
        tex = work / "diagram.tex"
        tex.write_text(source, encoding="utf-8")
        engine = shutil.which("lualatex") or shutil.which("pdflatex")
        if engine is None:
            raise SystemExit("lualatex or pdflatex is required to render a diagram")
        _run([engine, "-interaction=nonstopmode", "-halt-on-error", tex.name], work)
        pdf = work / "diagram.pdf"
        if not pdf.is_file():
            raise SystemExit(f"{Path(engine).name} did not write {pdf}")
        pdftocairo = shutil.which("pdftocairo")
        if pdftocairo is None:
            raise SystemExit("pdftocairo is required to write PNG and SVG")
        _run([pdftocairo, "-png", "-r", "160", "-singlefile", str(pdf), str(png.with_suffix(""))], work)
        produced = png.with_suffix(".png")
        if produced != png and produced.is_file():
            produced.replace(png)
        if svg is not None:
            svg = Path(svg).resolve()
            svg.parent.mkdir(parents=True, exist_ok=True)
            _run([pdftocairo, "-svg", str(pdf), str(svg)], work)


def render_animation(diagram: Path, out: Path) -> Path:
    from diagrams.manim_draw import render_manim

    drawing = resolve_drawing(load_diagram(diagram))
    return render_manim(drawing, Path(out))


def render_equation(tex: str, png: Path) -> None:
    """Render one displayed equation. physics and siunitx are loaded on purpose."""
    png = Path(png).resolve()
    png.parent.mkdir(parents=True, exist_ok=True)
    document = "\n".join([
        r"\documentclass[preview,border=12pt]{standalone}",
        r"\usepackage{amsmath,amssymb,physics,siunitx}",
        r"\begin{document}",
        r"\[" + tex + r"\]",
        r"\end{document}",
        "",
    ])
    with tempfile.TemporaryDirectory(prefix="equation-") as tmp:
        work = Path(tmp)
        (work / "eq.tex").write_text(document, encoding="utf-8")
        _run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "eq.tex"], work)
        pdf = work / "eq.pdf"
        _run(["pdftocairo", "-png", "-r", "180", "-singlefile", str(pdf), str(png.with_suffix(""))], work)


def _run(args: list[str], cwd: Path) -> None:
    completed = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if completed.returncode != 0:
        tail = (completed.stdout or "")[-2000:] + "\n" + (completed.stderr or "")[-2000:]
        raise SystemExit(f"{args[0]} failed:\n{tail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m diagrams")
    sub = parser.add_subparsers(dest="command", required=True)
    figure = sub.add_parser("figure", help="TikZ-Feynman PDF rendered to PNG and SVG")
    figure.add_argument("diagram", type=Path)
    figure.add_argument("-o", "--png", type=Path, required=True)
    figure.add_argument("--svg", type=Path)
    clip = sub.add_parser("animate", help="short Manim clip of the same diagram")
    clip.add_argument("diagram", type=Path)
    clip.add_argument("-o", "--out", type=Path, required=True)
    equation = sub.add_parser("equation", help="one LaTeX equation to PNG")
    equation.add_argument("tex")
    equation.add_argument("-o", "--png", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "figure":
        render_figure(args.diagram, args.png, args.svg)
    elif args.command == "animate":
        render_animation(args.diagram, args.out)
    else:
        render_equation(args.tex, args.png)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
