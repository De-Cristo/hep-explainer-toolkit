"""Planted diagram and citation errors, plus the UFO rules they sit on.

The planted scenes are ordinary scene files. The checker is not special-cased
for these strings: a wrong vertex fails because the SM UFO has no such
vertex, a flipped arrow fails because the PDG sign says the line is an
antifermion, and a missing citation fails because the claim has none.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from checks.citations import normalize_tex
from checks.diagrams import check_path
from checks.ufo_model import canonical_token, load_model, required_arrow

ROOT = Path(__file__).resolve().parents[2]

_QUOTE = (
    "q_1 (p_1) bar q_2 (p_2) to V-star to V H, as written for associated "
    "production in the public note this fixture stands in for."
)


def _write(folder: Path, name: str, text: str) -> None:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _excerpt(folder: Path, name: str, vertices: str, quote: str = _QUOTE) -> None:
    _write(
        folder,
        name,
        "arxiv: \"1610.07922\"\n"
        "locator: \"Section 3\"\n"
        f"quote: \"{quote}\"\n"
        "vertices:\n"
        + vertices,
    )


def _scene(folder: Path, body: str) -> Path:
    path = folder / "scene.yaml"
    path.write_text(body, encoding="utf-8")
    return path


class ModelRulesTest(unittest.TestCase):
    def test_ufo_rules_are_not_special_cases_for_w(self) -> None:
        model = load_model()
        self.assertTrue(model.allows(["q", "qbar'", "W"]).ok)
        self.assertTrue(model.allows(["u", "dbar", "W-"]).ok)
        self.assertTrue(model.allows(["d", "ubar", "W+"]).ok)
        self.assertFalse(model.allows(["u", "dbar", "W+"]).ok)
        self.assertTrue(model.allows(["q", "qbar", "Z"]).ok)
        self.assertTrue(model.allows(["nu", "nubar", "Z"]).ok)
        self.assertTrue(model.allows(["H", "b", "bbar"]).ok)
        self.assertTrue(model.allows(["W", "W", "H"]).ok)
        same = model.allows(["q", "qbar", "W"])
        self.assertFalse(same.ok)
        self.assertIn("charge", same.message)
        flavour = model.allows(["q", "qbar'", "Z"])
        self.assertFalse(flavour.ok)
        self.assertIn("no vertex", flavour.message)
        photon = model.allows(["nu", "nubar", "a"])
        self.assertFalse(photon.ok)
        self.assertIn("no vertex", photon.message)
        self.assertFalse(model.allows(["q", "qbar'", "gamma"]).ok)
        self.assertFalse(model.allows(["e-", "vmbar", "W"]).ok)
        self.assertFalse(model.allows(["H", "u", "ubar"]).ok)

    def test_antifermion_arrows_follow_the_pdg_sign(self) -> None:
        self.assertEqual(required_arrow("q"), "with_momentum")
        self.assertEqual(required_arrow("qbar'"), "against_momentum")
        self.assertEqual(required_arrow("bbar"), "against_momentum")
        self.assertEqual(required_arrow("e+"), "against_momentum")
        self.assertEqual(required_arrow("nubar"), "against_momentum")
        self.assertIsNone(required_arrow("W*"))
        self.assertIsNone(required_arrow("H"))
        self.assertEqual(canonical_token("q'bar"), canonical_token("qbar'"))
        self.assertNotEqual(canonical_token("qbar"), canonical_token("qbar'"))
        self.assertEqual(canonical_token("W*"), canonical_token("W"))
        self.assertEqual(canonical_token("gamma"), canonical_token("a"))

    def test_dawson_equations_normalize_into_the_quote(self) -> None:
        potential_quote = (
            r"V(\phi ) = + \mu^2 \phi ^{\dag}\phi  + \lambda (\phi ^{\dag}\phi )^2."
        )
        potential_tex = r"V(\phi)=+\mu^{2}\phi^{\dagger}\phi+\lambda(\phi^{\dagger}\phi)^{2}"
        self.assertIn(normalize_tex(potential_tex), normalize_tex(potential_quote))
        mass_quote = r"M_H = \sqrt{-2\mu^2} = \sqrt{2 \lambda} \nu"
        mass_tex = r"M_H=\sqrt{-2\mu^{2}}=\sqrt{2\lambda}\,\nu"
        self.assertIn(normalize_tex(mass_tex), normalize_tex(mass_quote))
        vev_quote = r"(\sqrt{2} G_F)^{-1/2} \simeq 246  \text{ GeV}"
        vev_tex = r"(\sqrt{2}G_F)^{-1/2}\simeq 246\,\text{GeV}"
        self.assertIn(normalize_tex(vev_tex), normalize_tex(vev_quote))


class PlantedSceneTest(unittest.TestCase):
    def test_wrong_vertex_with_a_real_looking_citation_fails(self) -> None:
        folder = Path(self.id().replace(".", "_"))
        # Kept out of the repo tree the confidentiality scan walks? This test
        # uses tmp via the id only if we write under /tmp. Use TemporaryDirectory.
        self._wrong(folder)

    def _wrong(self, _unused: Path) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _excerpt(
                folder,
                "excerpts/wrong.yaml",
                "  - [\"q\", \"qbar'\", \"a\"]\n  - [\"H\", \"b\", \"b\"]\n",
            )
            scene = _scene(
                folder,
                """
title: planted
scenes:
  - id: bad
    narration: "A flavour-changing photon and a Higgs decay to two bottom quarks."
    visual:
      kind: diagram
      diagram: diagram.yaml
    claims:
      - id: words
        kind: claim
        text: "A flavour-changing photon and a Higgs decay to two bottom quarks."
        citation:
          arxiv: "1610.07922"
          locator: "Section 3"
        excerpt: excerpts/wrong.yaml
      - id: graph
        kind: diagram
        citation:
          arxiv: "1610.07922"
          locator: "Section 3"
        excerpt: excerpts/wrong.yaml
""",
            )
            _write(
                folder,
                "diagram.yaml",
                """
vertices:
  - ["q", "qbar'", "a"]
  - ["H", "b", "b"]
lines:
  - id: q
    particle: q
    source: q
    target: v1
  - id: qbar
    particle: "qbar'"
    source: qbar
    target: v1
""",
            )
            report = check_path(scene)
        self.assertFalse(report.ok)
        model_rows = [row for row in report.rows if row.item.startswith("vertex") and row.status == "FAIL"]
        self.assertGreaterEqual(len(model_rows), 2)
        blob = " ".join(row.message for row in model_rows)
        self.assertTrue("no vertex" in blob or "charge" in blob)
        # The citation itself was accepted: the excerpt lists these vertices.
        graph = [row for row in report.rows if row.item == "graph"]
        self.assertTrue(graph and graph[0].status == "PASS")

    def test_flipped_antifermion_arrow_fails(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _excerpt(
                folder,
                "excerpts/ok.yaml",
                "  - [\"H\", \"b\", \"bbar\"]\n",
            )
            scene = _scene(
                folder,
                """
title: planted
scenes:
  - id: arrow
    narration: "The Higgs decays to a bottom quark and a bottom antiquark."
    visual:
      kind: diagram
      diagram: diagram.yaml
    claims:
      - id: words
        kind: claim
        text: "The Higgs decays to a bottom quark and a bottom antiquark."
        citation:
          arxiv: "1610.07922"
          locator: "Section 3"
        excerpt: excerpts/ok.yaml
      - id: graph
        kind: diagram
        citation:
          arxiv: "1610.07922"
          locator: "Section 3"
        excerpt: excerpts/ok.yaml
""",
            )
            _write(
                folder,
                "diagram.yaml",
                """
vertices:
  - id: v
    particles: ["H", "b", "bbar"]
lines:
  - id: b
    particle: b
    source: v
    target: b
  - id: bbar
    particle: bbar
    source: v
    target: bbar
    arrow: with_momentum
  - id: h
    particle: H
    source: h
    target: v
""",
            )
            report = check_path(scene)
        self.assertFalse(report.ok)
        arrows = [row for row in report.rows if row.item == "bbar"]
        self.assertTrue(arrows and arrows[0].status == "FAIL")
        self.assertIn("against_momentum", arrows[0].message)
        self.assertTrue(any(row.item == "vertex 1" and row.status == "PASS" for row in report.rows))

    def test_qqbar_instead_of_qqbar_prime_for_w_fails(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            # Excerpt agrees with the wrong diagram, so a citation match is not enough.
            _excerpt(
                folder,
                "excerpts/w.yaml",
                "  - [\"q\", \"qbar\", \"W\"]\n  - [\"W\", \"W\", \"H\"]\n",
            )
            scene = _scene(
                folder,
                """
title: planted
scenes:
  - id: wh
    narration: "A quark and an antiquark of the same flavour annihilate into a W."
    visual:
      kind: diagram
      diagram: diagram.yaml
    claims:
      - id: words
        kind: claim
        text: "A quark and an antiquark of the same flavour annihilate into a W."
        citation:
          arxiv: "1610.07922"
          locator: "Section 3"
        excerpt: excerpts/w.yaml
      - id: graph
        kind: diagram
        citation:
          arxiv: "1610.07922"
          locator: "Section 3"
        excerpt: excerpts/w.yaml
""",
            )
            _write(
                folder,
                "diagram.yaml",
                """
vertices:
  - ["q", "qbar", "W"]
  - ["W", "W", "H"]
""",
            )
            report = check_path(scene)
        self.assertFalse(report.ok)
        failed = [row for row in report.rows if row.status == "FAIL"]
        self.assertTrue(any("charge" in row.message for row in failed))
        self.assertTrue(any(row.item == "graph" and row.status == "PASS" for row in report.rows))

    def test_narration_without_a_citation_fails(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            scene = _scene(
                folder,
                """
title: planted
scenes:
  - id: bare
    narration: "The Higgs decays to two bottom quarks."
    visual:
      kind: slide
    claims: []
""",
            )
            report = check_path(scene)
        self.assertFalse(report.ok)
        self.assertTrue(any(row.item == "narration" and row.status == "FAIL" for row in report.rows))

    def test_equation_missing_from_the_excerpt_fails(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _write(
                folder,
                "excerpts/mass.yaml",
                "arxiv: \"0901.0241\"\n"
                "locator: \"eqch38\"\n"
                "quote: \"The second term in V represents a tree-level mass, but this quote never writes the formula.\"\n",
            )
            scene = _scene(
                folder,
                r"""
title: planted
scenes:
  - id: mass
    narration: "The Higgs mass is the square root of two lambda times v."
    visual:
      kind: slide
      equations:
        - id: mass
          tex: 'M_H=\sqrt{2\lambda}\,\nu'
    claims:
      - id: words
        kind: claim
        text: "The Higgs mass is the square root of two lambda times v."
        citation:
          arxiv: "0901.0241"
          locator: "eqch38"
        excerpt: excerpts/mass.yaml
      - id: mass
        kind: equation
        tex: 'M_H=\sqrt{2\lambda}\,\nu'
        citation:
          arxiv: "0901.0241"
          locator: "eqch38"
        excerpt: excerpts/mass.yaml
""",
            )
            report = check_path(scene)
        self.assertFalse(report.ok)
        self.assertTrue(any("does not appear" in row.message for row in report.rows))

    def test_cli_exit_codes(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            scene = _scene(
                folder,
                """
title: planted
scenes:
  - id: bare
    narration: "No citation is attached to this sentence at all."
    visual:
      kind: slide
    claims: []
""",
            )
            completed = subprocess.run(
                [sys.executable, "-m", "checks.diagrams", "check", str(scene)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("--- item ---", completed.stdout)
        self.assertIn("narration", completed.stdout)


class ExampleSceneTest(unittest.TestCase):
    def test_theory_examples_pass(self) -> None:
        for relative in (
            "examples/theory/vh/scene.yaml",
            "examples/theory/higgs/scene.yaml",
        ):
            path = ROOT / relative
            if not path.is_file():
                self.fail(f"missing example {relative}")
            report = check_path(path)
            failed = [row for row in report.rows if row.status == "FAIL"]
            self.assertFalse(failed, f"{relative}: " + "; ".join(row.message for row in failed))

    def test_wh_tikz_puts_antifermion_arrows_against_momentum(self) -> None:
        from checks.diagrams import load_diagram, resolve_drawing
        from diagrams.tikz import tikz_source

        drawing = resolve_drawing(load_diagram(ROOT / "examples/theory/vh/wh.yaml"))
        source = tikz_source(drawing)
        self.assertIn("(qbar) -- [anti fermion] (v1)", source)
        self.assertIn("(v3) -- [anti fermion] (bbar)", source)
        self.assertIn("(q) -- [fermion] (v1)", source)
        self.assertIn("(v3) -- [fermion] (b)", source)
        arrows = {line["id"]: line["arrow"] for line in drawing["lines"]}
        self.assertEqual(arrows["qbar_in"], "against_momentum")
        self.assertEqual(arrows["bbar_out"], "against_momentum")
        self.assertEqual(arrows["q_in"], "with_momentum")
        self.assertEqual(arrows["b_out"], "with_momentum")


if __name__ == "__main__":
    unittest.main()
