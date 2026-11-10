"""Tests for the YAML subset used by the check configs."""

from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from checks.yamlsubset import YamlError, load

ROOT = Path(__file__).resolve().parents[2]


class YamlSubsetTest(unittest.TestCase):
    def test_manifest_shape(self) -> None:
        text = """
        # comment
        match:
          rounding: half_up
          absolute_tolerance: 0
          relative_tolerance: 0
        sources:
          - id: toy_mass
            value: 1.2
            uncertainty: 0.05
            unit: GeV
            source:
              type: fit_json
              path: toy_fit.json
              key: mass
          - id: toy_yield
            value: 1.2e-3
            source:
              type: paper
              arxiv: "0000.00000"
        allow:
          - id: years
            kind: year
            min: 1990
            max: 2100
        flags: [true, false, null]
        """
        data = load(text)
        self.assertEqual(data["match"]["rounding"], "half_up")
        self.assertEqual(data["sources"][0]["value"], Decimal("1.2"))
        self.assertEqual(data["sources"][0]["uncertainty"], Decimal("0.05"))
        self.assertEqual(data["sources"][0]["source"]["key"], "mass")
        self.assertEqual(data["sources"][1]["value"], Decimal("1.2e-3"))
        self.assertEqual(data["allow"][0]["min"], 1990)
        self.assertEqual(data["flags"], [True, False, None])

    def test_single_quotes_keep_backslashes(self) -> None:
        data = load("pattern: '(?<![A-Za-z])\\\\s+'\n")
        self.assertIn("\\s", data["pattern"])

    def test_rejects_tabs_and_block_scalars(self) -> None:
        with self.assertRaises(YamlError):
            load("key:\n\tvalue\n")
        with self.assertRaises(YamlError):
            load("key: |\n  text\n")

    def test_real_configs_parse(self) -> None:
        markers = load((ROOT / "checks" / "config" / "markers.yaml").read_text(encoding="utf-8"))
        allow = load(
            (ROOT / "checks" / "config" / "traceability_allow.yaml").read_text(encoding="utf-8")
        )
        ids = {rule["id"] for rule in markers["rules"]}
        self.assertIn("cms_private_work", ids)
        self.assertIn("work_in_progress", ids)
        self.assertIn("HIG", markers["cadi"]["groups"])
        self.assertTrue(any(rule["id"] == "years" for rule in allow["allow"]))


if __name__ == "__main__":
    unittest.main()
