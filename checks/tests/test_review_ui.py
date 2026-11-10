"""Local reviewer UI security and decision-flow tests."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from checks.claims import load_registry
from checks.review import load_reviews, review_status
from checks.review_ui import (
    ReviewUIError,
    _handler_factory,
    apply_decision,
    render_html,
    review_model,
    validate_bind,
)
from checks.yamldump import dumps as dump_yaml


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _public_fixture(folder: Path) -> tuple[Path, Path, Path]:
    quote = (
        "This evidence quote contains <b>literal markup</b> and is deliberately "
        "long enough to test both escaping and the scientific review interface."
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
                    "id": "demo.claim",
                    "kind": "claim",
                    "origin": "theory",
                    "statement": "A reviewed statement with <script>unsafe markup</script>.",
                    "citation": {
                        "arxiv": "2110.11231",
                        "locator": "Section 9",
                    },
                    "excerpt": "excerpt.yaml",
                    "assumption_tags": ["reference_model"],
                    "caveats": ["Keep the stated scope."],
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
    scene = _write(
        folder / "scene.yaml",
        dump_yaml({
            "title": "review",
            "scenes": [
                {
                    "id": "one",
                    "narration": "Audience wording.",
                    "visual": {"kind": "slide"},
                    "claims": [
                        {
                            "id": "words",
                            "claim_ref": "demo.claim",
                            "text": "Audience-specific wording for the same claim.",
                        }
                    ],
                }
            ],
        }),
    )
    return registry, folder / "reviews.json", scene


def _private_registry(folder: Path) -> Path:
    source_quote = (
        "This private local source contains a long scientific statement used "
        "only to test that the review server never exposes private evidence remotely."
    )
    _write(folder / "private.txt", source_quote + "\n")
    _write(
        folder / "private-excerpt.yaml",
        dump_yaml({
            "local": "private.txt",
            "locator": "Section 1",
            "quote": source_quote,
        }),
    )
    return _write(
        folder / "private-claims.yaml",
        dump_yaml({
            "visibility": "private",
            "claims": [
                {
                    "id": "private.claim",
                    "kind": "claim",
                    "origin": "theory",
                    "statement": "A private scientific statement.",
                    "citation": {
                        "local": "private.txt",
                        "locator": "Section 1",
                    },
                    "excerpt": "private-excerpt.yaml",
                    "review": {
                        "source": "declared",
                        "evidence": "retrieved",
                        "value": "not_applicable",
                        "interpretation": "pending",
                    },
                }
            ],
        }),
    )


class ReviewModelTest(unittest.TestCase):
    def test_model_initializes_pending_reviews_and_links_audience_wording(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            registry, reviews, scene = _public_fixture(folder)
            model = review_model(registry, reviews, (scene,))
            persisted = load_reviews(reviews)
        self.assertEqual(model["claims"][0]["status"], "pending")
        self.assertEqual(
            model["claims"][0]["audience_wording"][0]["text"],
            "Audience-specific wording for the same claim.",
        )
        self.assertEqual(
            persisted["claims"]["demo.claim"]["decision"],
            "pending",
        )

    def test_approve_then_reject_are_both_hash_bound_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            registry_path, reviews, _scene = _public_fixture(folder)
            self.assertEqual(
                apply_decision(
                    registry_path,
                    reviews,
                    claim_id="demo.claim",
                    decision="approved",
                    reviewer="Physics Reviewer",
                    note="scope checked",
                ),
                "approved",
            )
            self.assertEqual(
                apply_decision(
                    registry_path,
                    reviews,
                    claim_id="demo.claim",
                    decision="rejected",
                    reviewer="Physics Reviewer",
                    note="wording overstates the evidence",
                ),
                "rejected",
            )
            registry = load_registry(registry_path)
            data = load_reviews(reviews)
            status = review_status(registry, data)["demo.claim"]
        self.assertEqual(status, "rejected")
        self.assertEqual(
            data["claims"]["demo.claim"]["note"],
            "wording overstates the evidence",
        )

    def test_html_escapes_scientific_text_and_contains_no_external_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            registry, reviews, scene = _public_fixture(folder)
            page = render_html(
                review_model(registry, reviews, (scene,)),
                "csrf-token",
            )
        self.assertNotIn("<script>unsafe", page)
        self.assertIn("&lt;script&gt;unsafe markup&lt;/script&gt;", page)
        self.assertIn("&lt;b&gt;literal markup&lt;/b&gt;", page)
        self.assertNotIn("<script src=", page)
        self.assertNotIn("<link rel=", page)


class BindSecurityTest(unittest.TestCase):
    def test_private_registry_can_never_bind_remote(self) -> None:
        with self.assertRaises(ReviewUIError):
            validate_bind(
                "0.0.0.0",
                visibility="private",
                unsafe_remote=True,
            )

    def test_public_remote_bind_requires_explicit_override(self) -> None:
        with self.assertRaises(ReviewUIError):
            validate_bind(
                "0.0.0.0",
                visibility="public",
                unsafe_remote=False,
            )
        validate_bind(
            "0.0.0.0",
            visibility="public",
            unsafe_remote=True,
        )

    def test_loopback_is_allowed(self) -> None:
        validate_bind(
            "127.0.0.1",
            visibility="private",
            unsafe_remote=False,
        )
        validate_bind(
            "::1",
            visibility="private",
            unsafe_remote=False,
        )


class HTTPBoundaryTest(unittest.TestCase):
    def test_csrf_headers_and_decision_post(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            registry, reviews, scene = _public_fixture(folder)
            csrf = "fixed-test-token"
            handler = _handler_factory(
                registry,
                reviews,
                (scene,),
                csrf,
                "Physics Reviewer",
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_address[1]
            root = f"http://127.0.0.1:{port}/"
            try:
                with urllib.request.urlopen(root, timeout=3) as response:
                    body = response.read().decode("utf-8")
                    self.assertEqual(
                        response.headers["Cache-Control"],
                        "no-store, max-age=0",
                    )
                    self.assertIn(
                        "default-src 'none'",
                        response.headers["Content-Security-Policy"],
                    )
                    self.assertIn("demo.claim", body)

                bad = urllib.parse.urlencode({
                    "csrf": "wrong",
                    "claim_id": "demo.claim",
                    "decision": "approved",
                    "reviewer": "Physics Reviewer",
                    "note": "checked",
                }).encode("utf-8")
                request = urllib.request.Request(
                    root + "decision",
                    data=bad,
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request, timeout=3)
                self.assertEqual(caught.exception.code, 403)

                good = urllib.parse.urlencode({
                    "csrf": csrf,
                    "claim_id": "demo.claim",
                    "decision": "approved",
                    "reviewer": "Physics Reviewer",
                    "note": "checked",
                }).encode("utf-8")
                request = urllib.request.Request(
                    root + "decision",
                    data=good,
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=3) as response:
                    body = response.read().decode("utf-8")
                    self.assertIn("demo.claim: approved", body)

                data = load_reviews(reviews)
                self.assertEqual(
                    data["claims"]["demo.claim"]["decision"],
                    "approved",
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_private_fixture_is_valid_but_remote_bind_policy_still_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = _private_registry(Path(tmp))
            registry = load_registry(registry_path)
        self.assertEqual(registry.visibility, "private")
        with self.assertRaises(ReviewUIError):
            validate_bind(
                "0.0.0.0",
                visibility=registry.visibility,
                unsafe_remote=True,
            )


if __name__ == "__main__":
    unittest.main()
