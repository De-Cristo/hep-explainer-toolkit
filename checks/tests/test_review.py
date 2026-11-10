"""Definition comparison, assumption propagation, and human review tests."""

from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from checks.claims import ClaimRegistryError, load_registry
from checks.review import (
    approve,
    claim_digest,
    load_reviews,
    make_review_file,
    review_status,
    strict_ready,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _excerpt(folder: Path, name: str, quote: str) -> Path:
    return _write(
        folder / name,
        textwrap.dedent(
            f"""
            arxiv: "2110.11231"
            locator: "Section 9"
            quote: "{quote}"
            """
        ),
    )


def _registry(folder: Path) -> Path:
    _excerpt(
        folder,
        "definition.yaml",
        "Polarization fractions are measured from angular coefficients in a specified phase space and reference frame.",
    )
    _excerpt(
        folder,
        "support.yaml",
        "Differential polarization measurements report fractions in bins of kinematic variables and depend on the selected phase space.",
    )
    return _write(
        folder / "claims.yaml",
        textwrap.dedent(
            """
            claims:
              - id: pol.fixed
                kind: definition
                origin: definition
                statement: "Definition A isolates a spin mixture under a fixed reference kinematic spectrum."
                citation:
                  arxiv: "2110.11231"
                  locator: "Section 9"
                excerpt: definition.yaml
                assumption_tags:
                  - reference_spectrum_fixed
                review:
                  source: declared
                  evidence: retrieved
                  value: not_applicable
                  interpretation: pending

              - id: pol.region
                kind: definition
                origin: definition
                statement: "Definition B reports the longitudinal fraction in a selected phase-space region."
                citation:
                  arxiv: "2110.11231"
                  locator: "Section 9"
                excerpt: definition.yaml
                assumption_tags:
                  - phase_space_weighting
                review:
                  source: declared
                  evidence: retrieved
                  value: not_applicable
                  interpretation: pending

              - id: pol.same_sm
                kind: claim
                origin: derived
                statement: "The two definitions can agree when the same reference spectrum describes the selected region."
                citation:
                  arxiv: "2110.11231"
                  locator: "Section 9"
                excerpt: support.yaml
                depends_on:
                  - pol.fixed
                  - pol.region
                assumptions:
                  - "The same reference weighting is used."
                review:
                  source: declared
                  evidence: retrieved
                  value: not_applicable
                  interpretation: pending

              - id: pol.diff_spectrum
                kind: claim
                origin: derived
                statement: "The definitions can differ when a changed production spectrum reweights regions with different spin composition."
                citation:
                  arxiv: "2110.11231"
                  locator: "Section 9"
                excerpt: support.yaml
                depends_on:
                  - pol.fixed
                  - pol.region
                assumption_tags:
                  - production_spectrum_model
                review:
                  source: declared
                  evidence: retrieved
                  value: not_applicable
                  interpretation: pending

            comparisons:
              - id: pol.two_definitions
                left: pol.fixed
                right: pol.region
                same_when:
                  - pol.same_sm
                differs_when:
                  - pol.diff_spectrum
            """
        ),
    )


class DefinitionAndReviewTest(unittest.TestCase):
    def test_assumptions_propagate_from_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = load_registry(_registry(Path(tmp)))
            effective = registry.effective_assumptions("pol.diff_spectrum")
        self.assertIn("reference_spectrum_fixed", effective)
        self.assertIn("phase_space_weighting", effective)
        self.assertIn("production_spectrum_model", effective)

    def test_comparison_requires_registered_support_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _registry(Path(tmp))
            text = path.read_text(encoding="utf-8").replace(
                "                  - pol.diff_spectrum",
                "                  - pol.missing",
            )
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(ClaimRegistryError):
                load_registry(path)

    def test_dependency_cycle_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _registry(Path(tmp))
            text = path.read_text(encoding="utf-8").replace(
                "                assumption_tags:\n"
                "                  - reference_spectrum_fixed",
                "                depends_on:\n"
                "                  - pol.same_sm\n"
                "                assumption_tags:\n"
                "                  - reference_spectrum_fixed",
                1,
            )
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(ClaimRegistryError):
                load_registry(path)

    def test_human_approval_is_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            path = _registry(folder)
            registry = load_registry(path)
            reviews = make_review_file(registry)
            for claim_id in registry.claims:
                approve(registry, reviews, claim_id, "Physics Reviewer", "checked")
            self.assertTrue(strict_ready(registry, reviews))
            old_digest = claim_digest(registry, "pol.fixed")

            excerpt = folder / "definition.yaml"
            excerpt.write_text(
                excerpt.read_text(encoding="utf-8")
                .replace("reference frame.", "reference frame with a clarified condition."),
                encoding="utf-8",
            )
            updated = load_registry(path)
            self.assertNotEqual(old_digest, claim_digest(updated, "pol.fixed"))
            status = review_status(updated, reviews)
            self.assertEqual(status["pol.fixed"], "stale")
            self.assertEqual(status["pol.same_sm"], "stale")
            self.assertEqual(status["pol.diff_spectrum"], "stale")
            self.assertFalse(strict_ready(updated, reviews))

    def test_review_file_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            registry = load_registry(_registry(folder))
            reviews = make_review_file(registry)
            out = folder / "reviews.json"
            out.write_text(json.dumps(reviews), encoding="utf-8")
            loaded = load_reviews(out)
        self.assertEqual(
            loaded["claims"]["pol.fixed"]["decision"],
            "pending",
        )


if __name__ == "__main__":
    unittest.main()
