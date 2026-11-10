"""v0.4 staged authoring workflow tests."""

from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from checks.authoring import (
    AuthoringError,
    index_source,
    load_pack,
    make_handoff,
    promote_candidate,
    sha256,
)
from checks.claims import load_registry
from checks.review import approve, make_review_file
from checks.yamldump import dumps as dump_yaml
from checks.yamlsubset import load as load_yaml


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _source(folder: Path) -> tuple[Path, str]:
    quote = (
        "The source states a deliberately long scientific sentence that "
        "supports the candidate claim and is suitable for exact evidence checking."
    )
    source = _write(
        folder / "source.txt",
        "# Overview\n\n" + quote + "\n\n## Validation\nAnother paragraph.\n",
    )
    return source, quote


def _private_pack(folder: Path, *, two: bool = False) -> Path:
    source, quote = _source(folder)
    candidates = [
        {
            "id": "draft.one",
            "proposed_claim_id": "demo.one",
            "kind": "definition",
            "origin": "definition",
            "statement": "A canonical definition promoted from a staged candidate.",
            "locator": "Section 1",
            "quote": quote,
            "assumption_tags": ["reference_convention"],
        }
    ]
    if two:
        candidates.append(
            {
                "id": "draft.two",
                "proposed_claim_id": "demo.two",
                "kind": "claim",
                "origin": "derived",
                "statement": "A dependent conclusion uses the promoted definition.",
                "locator": "Section 1",
                "quote": quote,
                "depends_on": ["demo.one"],
            }
        )
    data = {
        "schema_version": 1,
        "visibility": "private",
        "source": {
            "path": "source.txt",
            "sha256": sha256(source),
            "citation": {"local": "source.txt"},
        },
        "candidates": candidates,
    }
    return _write(folder / "candidates.yaml", dump_yaml(data))


def _handoff_fixture(folder: Path) -> tuple[Path, Path, Path]:
    quote = (
        "This public evidence sentence is deliberately long enough to support "
        "the canonical claim used by the approved authoring handoff test."
    )
    _write(
        folder / "excerpt.yaml",
        dump_yaml({
            "arxiv": "2110.11231",
            "locator": "Section 9",
            "quote": quote,
        }),
    )
    registry = _write(
        folder / "claims.yaml",
        dump_yaml({
            "claims": [
                {
                    "id": "demo.approved",
                    "kind": "claim",
                    "origin": "theory",
                    "statement": "The canonical reviewed statement is safe for authoring.",
                    "citation": {
                        "arxiv": "2110.11231",
                        "locator": "Section 9",
                    },
                    "excerpt": "excerpt.yaml",
                    "assumptions": ["The stated reference convention is used."],
                    "caveats": ["Audience wording still has to preserve the scope."],
                    "review": {
                        "source": "declared",
                        "evidence": "retrieved",
                        "value": "not_applicable",
                        "interpretation": "pending",
                    },
                }
            ]
        }),
    )
    _write(
        folder / "brief.yaml",
        dump_yaml({
            "topic": "Approved authoring handoff",
            "audience": {
                "profile": "hep_specialist",
                "knows": ["claim_review"],
                "introduce": ["approved_handoff"],
            },
            "purpose": "explain_reviewed_science",
            "medium": "slides",
            "learning_goal": "Use only reviewed scientific claims for downstream authoring.",
            "required_distinctions": [
                "A reviewed canonical claim and audience-specific wording are separate objects."
            ],
        }),
    )
    scene = _write(
        folder / "scene.yaml",
        dump_yaml({
            "title": "handoff",
            "brief": "brief.yaml",
            "claim_registry": "claims.yaml",
            "scenes": [
                {
                    "id": "one",
                    "question": "What science may the authoring agent use?",
                    "takeaway": "Only the reviewed claim enters the approved handoff.",
                    "requires": ["claim_review"],
                    "introduces": ["approved_handoff"],
                    "covers_distinctions": [
                        "A reviewed canonical claim and audience-specific wording are separate objects."
                    ],
                    "visual_purpose": "Keep canonical science and audience wording visibly separate.",
                    "narration": "The downstream authoring plan uses only a reviewed scientific claim.",
                    "visual": {"kind": "slide"},
                    "claims": [
                        {
                            "id": "words",
                            "claim_ref": "demo.approved",
                            "text": "The downstream authoring plan uses only a reviewed scientific claim.",
                        }
                    ],
                }
            ],
        }),
    )
    reviews = make_review_file(load_registry(registry))
    reviews_path = folder / "reviews.json"
    reviews_path.write_text(json.dumps(reviews), encoding="utf-8")
    return registry, scene, reviews_path


class AuthoringCandidateTest(unittest.TestCase):
    def test_source_index_finds_markdown_landmarks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source, _quote = _source(Path(tmp))
            index = index_source(source)
        self.assertEqual(index["line_count"], 6)
        self.assertEqual(
            [item["title"] for item in index["landmarks"]],
            ["Overview", "Validation"],
        )

    def test_changed_source_invalidates_candidate_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            pack = _private_pack(folder)
            load_pack(pack)
            source = folder / "source.txt"
            source.write_text(
                source.read_text(encoding="utf-8") + "changed\n",
                encoding="utf-8",
            )
            with self.assertRaises(AuthoringError):
                load_pack(pack)

    def test_quote_must_occur_in_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            pack = _private_pack(folder)
            data = load_yaml(pack.read_text(encoding="utf-8"))
            data["candidates"][0]["quote"] = (
                "This invented evidence sentence is long enough but does not "
                "occur anywhere in the source document used by the candidate."
            )
            pack.write_text(dump_yaml(data), encoding="utf-8")
            with self.assertRaises(AuthoringError):
                load_pack(pack)

    def test_promote_is_explicit_and_interpretation_stays_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            pack = _private_pack(folder)
            registry, excerpt = promote_candidate(
                pack,
                "draft.one",
                registry_path=folder / "claims.yaml",
                excerpt_dir=Path("excerpts"),
            )
            loaded = load_registry(registry)
            claim = loaded.get("demo.one")
        self.assertTrue(excerpt.name.endswith(".yaml"))
        self.assertEqual(claim.review["source"], "declared")
        self.assertEqual(claim.review["evidence"], "retrieved")
        self.assertEqual(claim.review["interpretation"], "pending")
        self.assertEqual(claim.citation["local"], "source.txt")

    def test_dependency_must_be_promoted_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            pack = _private_pack(folder, two=True)
            with self.assertRaises(AuthoringError):
                promote_candidate(
                    pack,
                    "draft.two",
                    registry_path=folder / "claims.yaml",
                    excerpt_dir=Path("excerpts"),
                )
            promote_candidate(
                pack,
                "draft.one",
                registry_path=folder / "claims.yaml",
                excerpt_dir=Path("excerpts"),
            )
            promote_candidate(
                pack,
                "draft.two",
                registry_path=folder / "claims.yaml",
                excerpt_dir=Path("excerpts"),
            )
            registry = load_registry(folder / "claims.yaml")
        self.assertEqual(registry.get("demo.two").depends_on, ("demo.one",))

    def test_yaml_writer_round_trips_nested_authoring_data(self) -> None:
        value = {
            "schema_version": 1,
            "source": {
                "citation": {"arxiv": "2110.11231"},
                "tags": [],
            },
            "candidates": [
                {
                    "id": "draft.one",
                    "assumptions": ["one", "two"],
                    "context": {"model": "SM"},
                }
            ],
        }
        self.assertEqual(load_yaml(dump_yaml(value)), value)


class ApprovedHandoffTest(unittest.TestCase):
    def test_pending_review_refuses_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _registry, scene, reviews = _handoff_fixture(folder)
            with self.assertRaises(AuthoringError):
                make_handoff(scene, reviews, folder / "handoff.json")

    def test_approved_claim_produces_handoff_without_raw_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            registry_path, scene, reviews_path = _handoff_fixture(folder)
            registry = load_registry(registry_path)
            reviews = json.loads(reviews_path.read_text(encoding="utf-8"))
            approve(
                registry,
                reviews,
                "demo.approved",
                "Physics Reviewer",
                "Approved for audience-specific authoring.",
            )
            reviews_path.write_text(json.dumps(reviews), encoding="utf-8")
            payload = make_handoff(
                scene,
                reviews_path,
                folder / "handoff.json",
            )
            raw = (folder / "handoff.json").read_text(encoding="utf-8")
        self.assertEqual(payload["claims"][0]["status"], "approved")
        self.assertEqual(payload["claims"][0]["id"], "demo.approved")
        self.assertIn("effective_assumptions", payload["claims"][0])
        self.assertNotIn("This public evidence sentence", raw)


if __name__ == "__main__":
    unittest.main()
