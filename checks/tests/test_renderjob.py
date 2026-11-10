"""Adversarial tests for the explicit renderer/checker contract."""

from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from checks.documents import document_from_lines
from checks.finaltext import FinalTextError, seal_render_job
from checks.renderjob import RenderInput, make_render_job


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _deck_manifest(*, fit: bool = False, include_narration: bool = True) -> str:
    narration_file = """
  - path: narration.txt
    source:
      type: arxiv
      arxiv: "1808.08242"
""" if include_narration else ""
    fit_file = """
  - path: fit.json
    source:
      type: arxiv
      arxiv: "1808.08242"
""" if fit else ""
    source = """
  - id: mass
    value: 125
    unit: GeV
    source:
      type: fit_json
      path: fit.json
      key: mass
""" if fit else """
  - id: mass
    value: 125
    unit: GeV
    source:
      type: paper
      arxiv: "1808.08242"
"""
    return textwrap.dedent(
        f"""
        files:
          - path: deck.html
            source:
              type: arxiv
              arxiv: "1808.08242"
        {narration_file}
        {fit_file}
        sources:
        {source}
        """
    )


class RenderJobIntegrityTest(unittest.TestCase):
    def test_external_narration_needs_its_own_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as root_tmp, tempfile.TemporaryDirectory() as ext_tmp:
            root = Path(root_tmp)
            external = Path(ext_tmp)
            slide = _write(root / "deck.html", "<div class='slide'>Public deck.</div>\n")
            _write(root / "sources.yaml", _deck_manifest(include_narration=False))
            narration = _write(external / "words.yaml", "The mass is 125 GeV.\n")
            job = make_render_job(
                root,
                [
                    RenderInput(slide, "slide"),
                    RenderInput(narration, "narration"),
                ],
                trace_documents=[
                    document_from_lines(narration, "narration", ["The mass is 125 GeV."])
                ],
            )
            with self.assertRaises(FinalTextError) as caught:
                seal_render_job(job)
        self.assertIn("undeclared", str(caught.exception))
        self.assertIn("narration", str(caught.exception))

    def test_external_narration_is_still_number_traced_after_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as root_tmp, tempfile.TemporaryDirectory() as ext_tmp:
            root = Path(root_tmp)
            external = Path(ext_tmp)
            slide = _write(root / "deck.html", "<div class='slide'>Public deck.</div>\n")
            _write(root / "sources.yaml", _deck_manifest())
            narration = _write(external / "words.yaml", "The mass is 987654 GeV.\n")
            _write(
                external / "sources.yaml",
                textwrap.dedent(
                    """
                    files:
                      - path: words.yaml
                        source:
                          type: arxiv
                          arxiv: "1808.08242"
                    """
                ),
            )
            job = make_render_job(
                root,
                [
                    RenderInput(slide, "slide"),
                    RenderInput(narration, "narration"),
                ],
                trace_documents=[
                    document_from_lines(
                        narration, "narration", ["The mass is 987654 GeV."]
                    )
                ],
            )
            with self.assertRaises(FinalTextError) as caught:
                seal_render_job(job)
        self.assertIn("traceability failed", str(caught.exception))
        self.assertIn("987654", str(caught.exception))

    def test_local_fit_file_is_part_of_the_render_seal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            slide = _write(root / "deck.html", "<div class='slide'>Mass 125 GeV.</div>\n")
            narration = _write(root / "narration.txt", "The mass is 125 GeV.\n")
            fit = _write(root / "fit.json", json.dumps({"mass": 125}) + "\n")
            _write(root / "sources.yaml", _deck_manifest(fit=True))
            job = make_render_job(
                root,
                [
                    RenderInput(slide, "slide"),
                    RenderInput(narration, "narration"),
                ],
                trace_documents=[
                    document_from_lines(slide, "slide", ["Mass 125 GeV."]),
                    document_from_lines(narration, "narration", ["The mass is 125 GeV."]),
                ],
            )
            seal = seal_render_job(job)
            self.assertIn(str(fit.resolve()), seal.hashes)
            fit.write_text(json.dumps({"mass": 126}) + "\n", encoding="utf-8")
            with self.assertRaises(FinalTextError):
                seal.assert_unchanged()

    def test_scene_narration_numbers_are_not_exempt_from_traceability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scene = _write(root / "scene.yaml", "title: test\nscenes: []\n")
            _write(
                root / "sources.yaml",
                textwrap.dedent(
                    """
                    sources:
                      - id: vev
                        value: 246
                        unit: GeV
                        source:
                          type: paper
                          arxiv: "0901.0241"
                    """
                ),
            )
            job = make_render_job(
                root,
                [RenderInput(scene, "scene")],
                trace_documents=[
                    document_from_lines(
                        scene, "narration", ["The vacuum value is 247 GeV."]
                    )
                ],
            )
            with self.assertRaises(FinalTextError) as caught:
                seal_render_job(job)
        self.assertIn("247", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
