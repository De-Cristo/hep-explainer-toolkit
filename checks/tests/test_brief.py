from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from checks.brief import BriefError, load_brief


class BriefTest(unittest.TestCase):
    def test_complete_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "brief.yaml"
            path.write_text(
                """topic: "Why use associated production to study H to bb?"
audience:
  profile: physics_undergraduate
  knows:
    - particle_decay
    - basic_probability
  introduce:
    - jets
    - flavour_tagging
purpose: explain_analysis_strategy
medium: slides
duration_minutes: 5
learning_goal: "Explain how accompanying particles help identify a Higgs candidate."
required_distinctions:
  - "A bottom quark and a reconstructed b-tagged jet are different objects."
avoid:
  - "Do not present an illustrative event as measured evidence."
""",
                encoding="utf-8",
            )
            brief = load_brief(path)
        self.assertEqual(brief.audience_profile, "physics_undergraduate")
        self.assertEqual(brief.medium, "slides")
        self.assertEqual(brief.duration_minutes, 5.0)
        self.assertIn("jets", brief.introduce)

    def test_missing_learning_goal_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "brief.yaml"
            path.write_text(
                """topic: test
audience:
  profile: public
purpose: explain
medium: video
""",
                encoding="utf-8",
            )
            with self.assertRaises(BriefError) as caught:
                load_brief(path)
        self.assertIn("learning_goal", str(caught.exception))

    def test_unknown_medium_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "brief.yaml"
            path.write_text(
                """topic: test
audience:
  profile: public
purpose: explain
medium: hologram
learning_goal: "Understand one idea."
""",
                encoding="utf-8",
            )
            with self.assertRaises(BriefError):
                load_brief(path)


if __name__ == "__main__":
    unittest.main()
