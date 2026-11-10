"""Approved-handoff integrity and reviewed slide-scaffold tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from checks.authoring import AuthoringError, make_handoff, verify_handoff
from checks.claims import load_registry
from checks.review import approve, make_review_file, reject, save_reviews
from checks.yamldump import dumps as dump_yaml
from checks.yamlsubset import load as load_yaml
from slides.cues import load_cue_map
from slides.scaffold import ScaffoldError, generate_scaffold
from video.deck import load_deck, walk_states


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _fixture(folder: Path) -> tuple[Path, Path, Path, Path]:
    quote_one = (
        "The first public evidence sentence is deliberately long enough to "
        "support the first reviewed scientific claim in the scaffold test."
    )
    quote_two = (
        "The second public evidence sentence is deliberately long enough to "
        "support the dependent reviewed scientific conclusion in the scaffold test."
    )
    _write(
        folder / "one.yaml",
        dump_yaml({
            "arxiv": "2110.11231",
            "locator": "Section 9",
            "quote": quote_one,
        }),
    )
    _write(
        folder / "two.yaml",
        dump_yaml({
            "arxiv": "2110.11231",
            "locator": "Section 10",
            "quote": quote_two,
        }),
    )
    registry_path = _write(
        folder / "claims.yaml",
        dump_yaml({
            "claims": [
                {
                    "id": "demo.definition",
                    "kind": "definition",
                    "origin": "definition",
                    "statement": "A reviewed definition anchors the explanation.",
                    "citation": {
                        "arxiv": "2110.11231",
                        "locator": "Section 9",
                    },
                    "excerpt": "one.yaml",
                    "assumption_tags": ["reference_convention"],
                    "review": {
                        "source": "declared",
                        "evidence": "retrieved",
                        "value": "not_applicable",
                        "interpretation": "pending",
                    },
                },
                {
                    "id": "demo.result",
                    "kind": "claim",
                    "origin": "derived",
                    "statement": "A reviewed conclusion depends on that definition.",
                    "citation": {
                        "arxiv": "2110.11231",
                        "locator": "Section 10",
                    },
                    "excerpt": "two.yaml",
                    "depends_on": ["demo.definition"],
                    "caveats": ["Keep the conclusion inside the stated scope."],
                    "review": {
                        "source": "declared",
                        "evidence": "retrieved",
                        "value": "not_applicable",
                        "interpretation": "pending",
                    },
                },
            ],
        }),
    )
    brief_path = _write(
        folder / "brief.yaml",
        dump_yaml({
            "topic": "Reviewed scaffold test",
            "audience": {
                "profile": "hep_specialist",
                "knows": ["reviewed_definition"],
                "introduce": ["reviewed_conclusion"],
            },
            "purpose": "explain_reviewed_result",
            "medium": "slides",
            "learning_goal": "Carry reviewed science into an editable slide scaffold.",
            "required_distinctions": [
                "A definition and a dependent conclusion are different scientific objects."
            ],
        }),
    )
    scene_path = _write(
        folder / "scene.yaml",
        dump_yaml({
            "title": "reviewed scaffold",
            "brief": "brief.yaml",
            "claim_registry": "claims.yaml",
            "scenes": [
                {
                    "id": "reviewed_scene",
                    "question": "How should reviewed science enter the deck?",
                    "takeaway": "The deck inherits reviewed statements and a visible scope boundary.",
                    "requires": ["reviewed_definition"],
                    "introduces": ["reviewed_conclusion"],
                    "covers_distinctions": [
                        "A definition and a dependent conclusion are different scientific objects."
                    ],
                    "visual_purpose": "Show the definition first, then reveal the dependent conclusion.",
                    "narration": [
                        {
                            "cue": "setup",
                            "text": "Start from the reviewed definition.",
                        },
                        {
                            "cue": "result",
                            "text": "Then reveal the reviewed dependent conclusion.",
                        },
                    ],
                    "visual": {
                        "kind": "slide",
                        "cues": [
                            {"id": "setup"},
                            {"id": "result"},
                        ],
                    },
                    "claims": [
                        {
                            "id": "definition",
                            "claim_ref": "demo.definition",
                            "text": "The reviewed definition anchors the explanation.",
                        },
                        {
                            "id": "result",
                            "claim_ref": "demo.result",
                            "text": "The dependent conclusion keeps its stated scope.",
                        },
                    ],
                }
            ],
        }),
    )
    registry = load_registry(registry_path)
    reviews = make_review_file(registry)
    for claim_id in registry.claims:
        approve(
            registry,
            reviews,
            claim_id,
            "Physics Reviewer",
            "Approved for scaffold test.",
        )
    reviews_path = folder / "reviews.json"
    save_reviews(reviews_path, reviews)

    template = _write(
        folder / "template.html",
        """<!doctype html>
<html><head><meta charset="utf-8"><title>{{TITLE_PLACEHOLDER}}</title></head>
<body>
<div>{{AUTHOR_PLACEHOLDER}} — {{EVENT_PLACEHOLDER}}</div>
<div class="slides-scroller">
<!-- END slides-scroller -->
</div>
</body></html>
""",
    )
    return scene_path, registry_path, reviews_path, template


def _approved_handoff(folder: Path) -> tuple[Path, Path, Path, Path, Path]:
    scene, registry, reviews, template = _fixture(folder)
    handoff = folder / "approved-authoring.json"
    make_handoff(scene, reviews, handoff)
    return handoff, scene, registry, reviews, template


class HandoffIntegrityTest(unittest.TestCase):
    def test_current_handoff_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handoff, _scene, _registry, _reviews, _template = _approved_handoff(Path(tmp))
            payload = verify_handoff(handoff)
        self.assertEqual(payload["kind"], "approved_authoring_handoff")
        self.assertEqual(len(payload["claims"]), 2)

    def test_manual_handoff_edit_fails_content_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handoff, _scene, _registry, _reviews, _template = _approved_handoff(Path(tmp))
            data = json.loads(handoff.read_text(encoding="utf-8"))
            data["scenes"][0]["takeaway"] = "tampered downstream wording"
            handoff.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(AuthoringError):
                verify_handoff(handoff)

    def test_scene_change_invalidates_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handoff, scene, _registry, _reviews, _template = _approved_handoff(Path(tmp))
            scene.write_text(
                scene.read_text(encoding="utf-8") + "\n# changed after approval\n",
                encoding="utf-8",
            )
            with self.assertRaises(AuthoringError):
                verify_handoff(handoff)

    def test_brief_change_invalidates_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            handoff, _scene, _registry, _reviews, _template = _approved_handoff(folder)
            brief = folder / "brief.yaml"
            brief.write_text(
                brief.read_text(encoding="utf-8")
                .replace("Reviewed scaffold test", "Changed reviewed scaffold test"),
                encoding="utf-8",
            )
            with self.assertRaises(AuthoringError):
                verify_handoff(handoff)

    def test_review_rejection_invalidates_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            handoff, _scene, registry_path, reviews_path, _template = _approved_handoff(folder)
            registry = load_registry(registry_path)
            reviews = json.loads(reviews_path.read_text(encoding="utf-8"))
            reject(
                registry,
                reviews,
                "demo.result",
                "Physics Reviewer",
                "Needs revision.",
            )
            save_reviews(reviews_path, reviews)
            with self.assertRaises(AuthoringError):
                verify_handoff(handoff)

    def test_evidence_change_invalidates_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            handoff, _scene, _registry, _reviews, _template = _approved_handoff(folder)
            excerpt = folder / "two.yaml"
            original = excerpt.read_text(encoding="utf-8")
            changed = original.replace(
                "in the scaffold test.",
                "in the scaffold test with an added qualification.",
            )
            self.assertNotEqual(original, changed)
            excerpt.write_text(changed, encoding="utf-8")
            with self.assertRaises(AuthoringError):
                verify_handoff(handoff)


class ReviewedScaffoldTest(unittest.TestCase):
    def test_scaffold_has_exact_semantic_walk_and_no_raw_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            handoff, _scene, _registry, _reviews, template = _approved_handoff(folder)
            out = folder / "deck"
            plan = generate_scaffold(
                handoff,
                out,
                template_path=template,
                author="Researcher",
                event="Internal authoring review",
            )
            deck = out / "deck.html"
            narration = load_yaml((out / "narration.yaml").read_text(encoding="utf-8"))
            cue_map = load_cue_map(deck)
            states = walk_states(load_deck(deck))
            raw_deck = deck.read_text(encoding="utf-8")

        self.assertFalse(plan["release_ready"])
        self.assertEqual(states, [(1, 0), (1, 1)])
        self.assertEqual(
            cue_map.resolve("reviewed_scene", "setup"),
            (1, 0),
        )
        self.assertEqual(
            cue_map.resolve("reviewed_scene", "result"),
            (1, 1),
        )
        self.assertEqual(
            [
                (item["scene"], item["cue"])
                for item in narration["steps"]
            ],
            [
                ("reviewed_scene", "setup"),
                ("reviewed_scene", "result"),
            ],
        )
        self.assertIn("AUTHORING SCAFFOLD", raw_deck)
        self.assertIn("Visual intent:", raw_deck)
        self.assertNotIn("The first public evidence sentence", raw_deck)
        self.assertNotIn("The second public evidence sentence", raw_deck)

    def test_scaffold_refuses_stale_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            handoff, scene, _registry, _reviews, template = _approved_handoff(folder)
            scene.write_text(
                scene.read_text(encoding="utf-8") + "\n# stale\n",
                encoding="utf-8",
            )
            with self.assertRaises(ScaffoldError):
                generate_scaffold(
                    handoff,
                    folder / "deck",
                    template_path=template,
                )

    def test_template_without_marker_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            handoff, _scene, _registry, _reviews, _template = _approved_handoff(folder)
            bad = _write(folder / "bad.html", "<html><body>no marker</body></html>")
            with self.assertRaises(ScaffoldError):
                generate_scaffold(
                    handoff,
                    folder / "deck",
                    template_path=bad,
                )


if __name__ == "__main__":
    unittest.main()
