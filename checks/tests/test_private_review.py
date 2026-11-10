"""Privacy-aware evidence, method-validation, and review-packet tests."""

from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from checks.claims import ClaimRegistryError, load_registry
from checks.release import build_packet
from checks.review import approve, claim_digest, make_review_file, review_status
from checks.storyboard import check_storyboard


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _private_registry(folder: Path, *, visibility: str = "private") -> Path:
    _write(
        folder / "source.txt",
        "Section 1. The local scientific statement is supported by this private "
        "reference text and is long enough to make the stored excerpt meaningful.\n",
    )
    _write(
        folder / "excerpt.yaml",
        """local: source.txt
locator: "Section 1"
quote: "The local scientific statement is supported by this private reference text and is long enough to make the stored excerpt meaningful."
""",
    )
    return _write(
        folder / "claims.yaml",
        textwrap.dedent(
            f"""
            visibility: {visibility}
            claims:
              - id: private.definition
                kind: definition
                origin: definition
                statement: "A private definition used only inside the protected project."
                citation:
                  local: source.txt
                  locator: "Section 1"
                excerpt: excerpt.yaml
                assumption_tags:
                  - private_reference_convention
                review:
                  source: declared
                  evidence: retrieved
                  value: not_applicable
                  interpretation: pending
            """
        ),
    )


def _public_review_fixture(folder: Path) -> tuple[Path, Path]:
    _write(
        folder / "excerpt.yaml",
        """arxiv: "2110.11231"
locator: "Section 9"
quote: "This public evidence excerpt is deliberately long enough to support the review-packet claim used in this test."
""",
    )
    registry = _write(
        folder / "claims.yaml",
        textwrap.dedent(
            """
            claims:
              - id: demo.method
                kind: claim
                origin: measurement
                statement: "The validation test checks the stated method property."
                citation:
                  arxiv: "2110.11231"
                  locator: "Section 9"
                excerpt: excerpt.yaml
                review:
                  source: declared
                  evidence: retrieved
                  value: not_applicable
                  interpretation: pending
              - id: demo.result
                kind: claim
                origin: derived
                statement: "The test demonstrates one bounded conclusion."
                citation:
                  arxiv: "2110.11231"
                  locator: "Section 9"
                excerpt: excerpt.yaml
                depends_on:
                  - demo.method
                review:
                  source: declared
                  evidence: retrieved
                  value: not_applicable
                  interpretation: pending
              - id: demo.limit
                kind: claim
                origin: derived
                statement: "The test does not establish a broader conclusion."
                citation:
                  arxiv: "2110.11231"
                  locator: "Section 9"
                excerpt: excerpt.yaml
                review:
                  source: declared
                  evidence: retrieved
                  value: not_applicable
                  interpretation: pending
            """
        ),
    )
    brief = _write(
        folder / "brief.yaml",
        textwrap.dedent(
            """
            topic: "Bounded method validation"
            audience:
              profile: hep_specialist
              knows:
                - method
              introduce:
                - validation_scope
            purpose: explain_validation
            medium: slides
            learning_goal: "State what a validation test demonstrates and what it does not establish."
            required_distinctions:
              - "A validation result and a broader physics conclusion are different claims."
            """
        ),
    )
    scene = _write(
        folder / "scene.yaml",
        textwrap.dedent(
            """
            title: validation
            brief: brief.yaml
            claim_registry: claims.yaml
            scenes:
              - id: validation
                question: "What does this test establish?"
                takeaway: "The test supports one bounded conclusion and leaves a broader claim untested."
                requires:
                  - method
                introduces:
                  - validation_scope
                covers_distinctions:
                  - "A validation result and a broader physics conclusion are different claims."
                visual_purpose: "Keep the method result and its interpretation boundary together."
                narration: "The validation test checks the stated method property."
                visual:
                  kind: slide
                claims:
                  - id: words
                    claim_ref: demo.method
                    text: "The validation test checks the stated method property."
                method_validation:
                  test: demo.method
                  demonstrates:
                    - demo.result
                  does_not_establish:
                    - demo.limit
            """
        ),
    )
    return registry, scene


class PrivateEvidenceTest(unittest.TestCase):
    def test_private_registry_accepts_exact_local_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = load_registry(_private_registry(Path(tmp)))
        self.assertEqual(registry.visibility, "private")
        self.assertEqual(
            registry.get("private.definition").citation["local"],
            "source.txt",
        )

    def test_public_registry_rejects_local_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ClaimRegistryError):
                load_registry(_private_registry(Path(tmp), visibility="public"))

    def test_private_excerpt_must_exist_in_local_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            path = _private_registry(folder)
            (folder / "excerpt.yaml").write_text(
                """local: source.txt
locator: "Section 1"
quote: "This invented private quote is deliberately long enough but does not exist anywhere in the source document."
""",
                encoding="utf-8",
            )
            with self.assertRaises(ClaimRegistryError):
                load_registry(path)

    def test_local_source_change_stales_human_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            path = _private_registry(folder)
            registry = load_registry(path)
            reviews = make_review_file(registry)
            approve(
                registry,
                reviews,
                "private.definition",
                "Private Reviewer",
                "checked against local note",
            )
            original = claim_digest(registry, "private.definition")
            source = folder / "source.txt"
            source.write_text(
                source.read_text(encoding="utf-8")
                + "Section 2. A new private source paragraph changes the evidence bytes.\n",
                encoding="utf-8",
            )
            updated = load_registry(path)
            self.assertNotEqual(
                original,
                claim_digest(updated, "private.definition"),
            )
            self.assertEqual(
                review_status(updated, reviews)["private.definition"],
                "stale",
            )


class MethodValidationAndPacketTest(unittest.TestCase):
    def test_method_validation_boundary_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _registry, scene = _public_review_fixture(Path(tmp))
            report = check_storyboard(scene)
        self.assertTrue(report.ok, report.problems)

    def test_method_validation_requires_limit_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _registry, scene = _public_review_fixture(Path(tmp))
            original = scene.read_text(encoding="utf-8")
            text = original.replace(
                "      does_not_establish:\n"
                "        - demo.limit\n",
                "",
            )
            self.assertNotEqual(original, text)
            scene.write_text(text, encoding="utf-8")
            report = check_storyboard(scene)
        self.assertFalse(report.ok)
        self.assertTrue(
            any("does_not_establish" in item for item in report.problems)
        )

    def test_review_packet_becomes_ready_after_explicit_approvals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            registry_path, scene = _public_review_fixture(folder)
            registry = load_registry(registry_path)
            reviews = make_review_file(registry)
            reviews_path = folder / "reviews.json"
            reviews_path.write_text(json.dumps(reviews), encoding="utf-8")

            first = build_packet(
                scene,
                folder / "before.html",
                reviews_path=reviews_path,
            )
            self.assertFalse(first["review_ready"])
            self.assertFalse(first["release_ready"])

            for claim_id in registry.claims:
                approve(registry, reviews, claim_id, "Physics Reviewer", "approved")
            reviews_path.write_text(json.dumps(reviews), encoding="utf-8")
            second = build_packet(
                scene,
                folder / "after.html",
                reviews_path=reviews_path,
            )
            self.assertTrue(second["review_ready"])
            self.assertFalse(second["release_ready"])
            packet = (folder / "after.html").read_text(encoding="utf-8")
            self.assertIn("Does not establish", packet)
            self.assertIn("Effective assumptions", packet)

    def test_public_packet_requires_and_passes_public_renderer_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            registry_path, scene = _public_review_fixture(folder)
            _write(folder / "sources.yaml", "sources: []\n")
            registry = load_registry(registry_path)
            reviews = make_review_file(registry)
            for claim_id in registry.claims:
                approve(registry, reviews, claim_id, "Physics Reviewer", "approved")
            reviews_path = folder / "reviews.json"
            reviews_path.write_text(json.dumps(reviews), encoding="utf-8")
            summary = build_packet(
                scene,
                folder / "public.html",
                reviews_path=reviews_path,
                public=True,
            )
        self.assertTrue(summary["review_ready"])
        self.assertTrue(summary["release_ready"])
        self.assertIsNone(summary["public_validation_error"])

    def test_public_packet_refuses_private_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            registry = _private_registry(folder)
            _write(
                folder / "brief.yaml",
                """topic: private
audience:
  profile: hep_specialist
  knows:
    - private_definition
  introduce:
    - reviewed_definition
purpose: review
medium: slides
learning_goal: "Review a private scientific definition."
required_distinctions:
  - "Private evidence is not public evidence."
""",
            )
            scene = _write(
                folder / "scene.yaml",
                """title: private
brief: brief.yaml
claim_registry: claims.yaml
scenes:
  - id: one
    question: "What definition is used?"
    takeaway: "This definition remains private."
    requires:
      - private_definition
    introduces:
      - reviewed_definition
    covers_distinctions:
      - "Private evidence is not public evidence."
    visual_purpose: "Show the definition without publishing its source."
    narration: "A private definition used only inside the protected project."
    visual:
      kind: slide
    claims:
      - id: words
        claim_ref: private.definition
        text: "A private definition used only inside the protected project."
""",
            )
            with self.assertRaises(Exception):
                build_packet(scene, folder / "public.html", public=True)


if __name__ == "__main__":
    unittest.main()
