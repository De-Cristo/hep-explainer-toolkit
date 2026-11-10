"""Draw a resolved diagram with Manim. Arrows come from the spec unchanged."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from diagrams.labels import latex_label


def render_manim(drawing: dict, out: Path) -> Path:
    from manim import (
        Arrow,
        Create,
        DashedLine,
        Dot,
        MathTex,
        ParametricFunction,
        Scene,
        WHITE,
        config,
        tempconfig,
    )

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    media = out.parent / "manim-media"

    class DiagramScene(Scene):
        def construct(self) -> None:
            positions = {
                str(name): _point(coords)
                for name, coords in (drawing.get("positions") or {}).items()
            }
            dots = []
            for line in drawing["lines"]:
                start = positions[str(line["source"])]
                end = positions[str(line["target"])]
                mob = _line(line, start, end, Arrow, DashedLine, ParametricFunction)
                label = MathTex(latex_label(line["particle"])).scale(0.7)
                label.next_to(mob, _side(start, end), buff=0.12)
                self.play(Create(mob), Create(label), run_time=0.7)
                if _is_vertex(drawing, line["target"]):
                    dot = Dot(end, radius=0.05, color=WHITE)
                    dots.append(dot)
                    self.add(dot)
            self.wait(0.4)

    with tempconfig({
        "quality": "low_quality",
        "preview": False,
        "media_dir": str(media),
        "output_file": out.stem,
        "disable_caching": True,
        "write_to_movie": True,
    }):
        # low_quality is 480p15. The assembler scales the clip to the narration.
        config.pixel_width = 854
        config.pixel_height = 480
        scene = DiagramScene()
        scene.render()
    movie = _find_movie(media, out.stem)
    if movie.resolve() != out.resolve():
        movie.replace(out)
    return out


def _point(coords) -> np.ndarray:
    return np.array([float(coords[0]) * 0.85, float(coords[1]) * 0.85, 0.0])


def _is_vertex(drawing: dict, name: str) -> bool:
    degree = 0
    for line in drawing["lines"]:
        if str(line["source"]) == name or str(line["target"]) == name:
            degree += 1
    return degree > 1


def _side(start: np.ndarray, end: np.ndarray) -> np.ndarray:
    direction = end - start
    length = float(np.linalg.norm(direction[:2])) or 1.0
    unit = direction / length
    return np.array([-unit[1], unit[0], 0.0])


def _line(line, start, end, arrow_cls, dashed_cls, parametric_cls):
    from manim import BLUE, GREEN, ORANGE, YELLOW

    particle = str(line["particle"]).rstrip("*")
    kind = particle.lower()
    if line["arrow"] in {"with_momentum", "against_momentum"}:
        tail, tip = (start, end) if line["arrow"] == "with_momentum" else (end, start)
        color = BLUE if "q" in kind else ORANGE
        return arrow_cls(tail, tip, buff=0, color=color, stroke_width=3, max_tip_length_to_length_ratio=0.12)
    if kind.startswith("h"):
        return dashed_cls(start, end, color=GREEN, stroke_width=3, dash_length=0.12)
    return _wavy(start, end, parametric_cls, YELLOW)


def _wavy(start, end, parametric_cls, color):
    start = np.array(start, dtype=float)
    end = np.array(end, dtype=float)
    direction = end - start
    length = float(np.linalg.norm(direction)) or 1.0
    unit = direction / length
    perp = np.array([-unit[1], unit[0], 0.0])
    waves = 4

    def param(t: float) -> np.ndarray:
        return start + t * direction + 0.12 * np.sin(t * waves * np.pi * 2) * perp

    return parametric_cls(param, t_range=(0, 1, 0.02), color=color, stroke_width=3)


def _find_movie(media: Path, stem: str) -> Path:
    found = sorted(media.rglob(f"{stem}.mp4"))
    if not found:
        found = sorted(media.rglob("*.mp4"))
    if not found:
        raise SystemExit(f"Manim did not write a movie under {media}")
    return found[-1]
