from __future__ import annotations

import unittest

from video.qa import _issues


class VisualQATest(unittest.TestCase):
    def test_issue_summary_collects_readiness_images_and_overflow(self) -> None:
        finding = {
            "ready": False,
            "brokenImages": ["missing.png"],
            "overflow": [
                {
                    "tag": "img",
                    "class": "plot",
                    "left": -5,
                    "top": 10,
                    "right": 1900,
                    "bottom": 900,
                }
            ],
            "errors": ["custom renderer warning"],
        }
        issues = _issues(finding)
        self.assertTrue(any("content-ready" in item for item in issues))
        self.assertTrue(any("missing.png" in item for item in issues))
        self.assertTrue(any("overflow" in item for item in issues))
        self.assertTrue(any("custom renderer warning" in item for item in issues))

    def test_clean_state_has_no_issues(self) -> None:
        self.assertEqual(
            _issues({
                "ready": True,
                "brokenImages": [],
                "overflow": [],
                "errors": [],
            }),
            [],
        )


if __name__ == "__main__":
    unittest.main()
