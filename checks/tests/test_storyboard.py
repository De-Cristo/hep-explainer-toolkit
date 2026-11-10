"""Audience-linked storyboard and semantic-cue tests."""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from checks.storyboard import check_storyboard
from diagrams.states import cue_drawing

ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _fixture(
    folder: Path,
    *,
    requires: str = "known",
    cover: bool = True,
    line_id: str = "incoming",
) -> Path:
    _write(
        folder / "brief.yaml",
        textwrap.dedent(
            """
            topic: "Test explanation"
            audience:
              profile: physics_student
              knows:
                - known
              introduce:
                - new_concept
            purpose: explain
            medium: video
            learning_goal: "Understand the transition from known to new_concept."
            required_distinctions:
              - "Known and new_concept are different."
            """
        ),
    )
    _write(
        folder / "diagram.yaml",
        textwrap.dedent(
            """
            positions:
              a: [0, 0]
              v: [1, 0]
            vertices:
              - id: v
                particles: ["H", "b", "bbar"]
            lines:
              - id: incoming
                particle: H
                source: a
                target: v
            """
        ),
    )
    lines = [
        "title: test",
        "brief: brief.yaml",
        "scenes:",
        "  - id: one",
        '    question: "What new idea follows?"',
        '    takeaway: "The new concept follows from the declared prerequisite."',
        "    requires:",
        f"      - {requires}",
        "    introduces:",
        "      - new_concept",
    ]
    if cover:
        lines.extend([
            "    covers_distinctions:",
            '      - "Known and new_concept are different."',
        ])
    lines.extend([
        '    visual_purpose: "Reveal the relevant diagram state."',
        "    narration:",
        "      - cue: first",
        '        text: "This segment introduces the new concept."',
        "    visual:",
        "      kind: diagram",
        "      diagram: diagram.yaml",
        "      cues:",
        "        - id: first",
        "          show_lines:",
        f"            - {line_id}",
        "    claims: []",
    ])
    return _write(folder / "scene.yaml", "\n".join(lines) + "\n")


class StoryboardTest(unittest.TestCase):
    def test_valid_reasoning_chain_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = check_storyboard(_fixture(Path(tmp)))
        self.assertTrue(report.ok, report.problems)

    def test_unknown_prerequisite_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = check_storyboard(_fixture(Path(tmp), requires="missing"))
        self.assertFalse(report.ok)
        self.assertTrue(any("not yet known" in item for item in report.problems))

    def test_required_distinction_must_be_covered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = check_storyboard(_fixture(Path(tmp), cover=False))
        self.assertFalse(report.ok)
        self.assertTrue(any("required distinctions not covered" in item for item in report.problems))

    def test_unknown_diagram_line_id_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = check_storyboard(_fixture(Path(tmp), line_id="not_a_line"))
        self.assertFalse(report.ok)
        self.assertTrue(any("unknown diagram line" in item for item in report.problems))

    def test_narration_cue_must_have_a_visual_cue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            scene = _fixture(folder)
            text = scene.read_text(encoding="utf-8").replace(
                "        - id: first\n",
                "        - id: other\n",
            )
            scene.write_text(text, encoding="utf-8")
            report = check_storyboard(scene)
        self.assertFalse(report.ok)
        self.assertTrue(any("no visual cue" in item for item in report.problems))

    def test_vh_example_storyboard_passes(self) -> None:
        report = check_storyboard(ROOT / "examples/theory/vh/scene.yaml")
        self.assertTrue(report.ok, "; ".join(report.problems))

    def test_cue_drawing_selects_only_named_lines(self) -> None:
        drawing = {
            "vertices": [["H", "b", "bbar"]],
            "positions": {"a": [0, 0], "b": [1, 0]},
            "lines": [
                {"id": "incoming", "particle": "H", "source": "a", "target": "b", "arrow": "none"},
                {"id": "complete", "particle": "H", "source": "b", "target": "a", "arrow": "none"},
            ],
        }
        selected = cue_drawing(drawing, ["incoming"])
        self.assertEqual([line["id"] for line in selected["lines"]], ["incoming"])
        all_lines = cue_drawing(drawing, "all")
        self.assertEqual(len(all_lines["lines"]), 2)


if __name__ == "__main__":
    unittest.main()
