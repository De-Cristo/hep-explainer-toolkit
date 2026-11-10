"""Reusable scientific claim registry and scene-link tests."""

from __future__ import annotations

import io
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from checks.claims import ClaimRegistryError, format_review, load_registry, main
from checks.diagrams import check_path


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _excerpt(folder: Path) -> Path:
    return _write(
        folder / "excerpt.yaml",
        textwrap.dedent(
            """
            arxiv: "1610.07922"
            locator: "Section 3"
            quote: "This stored public excerpt is deliberately long enough to support a reusable qualitative scientific claim."
            """
        ),
    )


def _registry(folder: Path, *, interpretation: str = "pending") -> Path:
    _excerpt(folder)
    return _write(
        folder / "claims.yaml",
        textwrap.dedent(
            f"""
            claims:
              - id: demo.stable
                kind: claim
                origin: theory
                statement: "The canonical scientific statement is stable across audience variants."
                citation:
                  arxiv: "1610.07922"
                  locator: "Section 3"
                excerpt: excerpt.yaml
                context:
                  model: SM
                assumptions:
                  - "This is a controlled test claim."
                caveats:
                  - "Audience wording still needs human review."
                review:
                  source: declared
                  evidence: retrieved
                  value: not_applicable
                  interpretation: {interpretation}
            """
        ),
    )


class ClaimRegistryTest(unittest.TestCase):
    def test_registry_keeps_review_dimensions_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = load_registry(_registry(Path(tmp)))
            claim = registry.get("demo.stable")
            review = format_review(registry)
        self.assertEqual(claim.review["source"], "declared")
        self.assertEqual(claim.review["evidence"], "retrieved")
        self.assertEqual(claim.review["value"], "not_applicable")
        self.assertEqual(claim.review["interpretation"], "pending")
        self.assertFalse(claim.strict_ready)
        self.assertIn("Strict release ready: **no**", review)

    def test_strict_mode_requires_interpretation_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            pending = _registry(folder)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["check", str(pending), "--strict"]), 1)
            ready = _registry(folder, interpretation="reviewed")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["check", str(ready), "--strict"]), 0)

    def test_number_claim_cannot_mark_value_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _excerpt(folder)
            path = _write(
                folder / "claims.yaml",
                textwrap.dedent(
                    """
                    claims:
                      - id: demo.number
                        kind: number
                        origin: measurement
                        statement: "A test value is 125 GeV."
                        value: 125
                        unit: GeV
                        citation:
                          arxiv: "1610.07922"
                          locator: "Section 3"
                        excerpt: excerpt.yaml
                        review:
                          source: declared
                          evidence: retrieved
                          value: not_applicable
                          interpretation: pending
                    """
                ),
            )
            with self.assertRaises(ClaimRegistryError):
                load_registry(path)

    def test_scene_resolves_evidence_from_claim_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _registry(folder)
            scene = _write(
                folder / "scene.yaml",
                textwrap.dedent(
                    """
                    title: demo
                    claim_registry: claims.yaml
                    scenes:
                      - id: intro
                        narration: "Audience wording can differ while the scientific evidence stays central."
                        visual:
                          kind: slide
                        claims:
                          - id: words
                            claim_ref: demo.stable
                            text: "Audience wording can differ while the scientific evidence stays central."
                    """
                ),
            )
            report = check_path(scene)
        failed = [row for row in report.rows if row.status == "FAIL"]
        self.assertFalse(failed, "; ".join(row.message for row in failed))
        row = next(row for row in report.rows if row.item == "words")
        self.assertIn("claim_ref demo.stable", row.message)
        self.assertIn("canonical claim:", row.excerpt_body)

    def test_scene_must_not_duplicate_registry_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _registry(folder)
            scene = _write(
                folder / "scene.yaml",
                textwrap.dedent(
                    """
                    title: demo
                    claim_registry: claims.yaml
                    scenes:
                      - id: intro
                        narration: "The canonical scientific statement is stable across audience variants."
                        visual:
                          kind: slide
                        claims:
                          - id: words
                            claim_ref: demo.stable
                            text: "The canonical scientific statement is stable across audience variants."
                            citation:
                              arxiv: "1610.07922"
                              locator: "Section 3"
                    """
                ),
            )
            with self.assertRaises(Exception) as caught:
                check_path(scene)
        self.assertIn("do not duplicate registry evidence", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
