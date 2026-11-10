"""Number traceability: toy values only, including a misread narration."""

from __future__ import annotations

import io
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from decimal import Decimal
from pathlib import Path

from checks.documents import Document, Region, load_document
from checks.numbers import extract_numbers
from checks.traceability import ManifestError, check, load_manifest, main

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TraceabilityFixtureTest(unittest.TestCase):
    def test_toy_deck_passes_and_reports_exemptions(self) -> None:
        folder = FIXTURES / "trace_pass"
        report = check(folder, folder / "sources.yaml")
        self.assertEqual(report.failures, [], _failures(report))
        self.assertEqual(report.source_errors, [])
        rules = {item.rule_id for item in report.exemptions}
        self.assertIn("slide_numbers", rules)
        self.assertIn("years", rules)
        self.assertIn("arxiv", rules)
        # The spoken luminosity and the numeric luminosity both matched.
        surfaces = " ".join(item.surface for item in report.matches)
        self.assertIn("one hundred thirty-eight inverse femtobarns", surfaces)
        self.assertIn("13.6 TeV", surfaces)
        self.assertIn("one point two", surfaces)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["check", str(folder)]), 0)

    def test_misread_narration_and_unknown_slide_number_fail(self) -> None:
        folder = FIXTURES / "trace_fail"
        report = check(folder, folder / "sources.yaml")
        self.assertFalse(report.ok)
        narration = [item for item in report.failures if item.kind == "narration"]
        slides = [item for item in report.failures if item.kind == "slide"]
        self.assertTrue(any("1.3" in item.value and "GeV" in item.value for item in narration))
        self.assertTrue(any("one point three" in item.surface for item in narration))
        self.assertTrue(any("toy_mass" in item.nearest for item in narration))
        self.assertTrue(any(item.value.startswith("99.9") for item in slides))
        # The correctly spoken luminosity is still matched.
        self.assertTrue(
            any("one hundred thirty-eight" in item.surface for item in report.matches)
        )
        with redirect_stdout(io.StringIO()):
            self.assertEqual(
                main(["check", str(folder), "--manifest", str(folder / "sources.yaml")]),
                1,
            )


class NumberParserTest(unittest.TestCase):
    def test_spoken_and_scientific_forms(self) -> None:
        text = "\n".join(
            [
                "one point two",
                "thirteen point six teraelectronvolts",
                "one hundred thirty-eight inverse femtobarns",
                "twelve point five percent",
                "1.2e-3",
                "1.2 × 10^{-3}",
                "1.2 +0.3 -0.1 GeV",
                "two jets",
                "version 1.2.3",
            ]
        )
        hits = _hits(text)
        by_surface = {hit.surface: hit for hit in hits}
        self.assertEqual(by_surface["one point two"].value, Decimal("1.2"))
        energy = by_surface["thirteen point six teraelectronvolts"]
        self.assertEqual(energy.value, Decimal("13.6"))
        self.assertEqual(energy.unit, "TeV")
        lumi = by_surface["one hundred thirty-eight inverse femtobarns"]
        self.assertEqual(lumi.value, Decimal("138"))
        self.assertEqual(lumi.unit, "fb-1")
        percent = by_surface["twelve point five percent"]
        self.assertEqual(percent.value, Decimal("12.5"))
        self.assertEqual(percent.unit, "%")
        self.assertEqual(by_surface["1.2e-3"].value, Decimal("0.0012"))
        self.assertEqual(by_surface["1.2 × 10^{-3}"].value, Decimal("0.0012"))
        asym = next(hit for hit in hits if hit.uncertainty_up is not None)
        self.assertEqual(asym.value, Decimal("1.2"))
        self.assertEqual(asym.uncertainty_up, Decimal("0.3"))
        self.assertEqual(asym.uncertainty_down, Decimal("0.1"))
        self.assertEqual(asym.unit, "GeV")
        self.assertNotIn("two jets", by_surface)
        self.assertTrue(any("version" in hit.hints for hit in hits))

    def test_misread_does_not_round_onto_the_manifest(self) -> None:
        folder = _deck(
            slide="The toy mass is 1.2 GeV.",
            narration="The toy mass is one point three gigaelectronvolts.",
            manifest=textwrap.dedent(
                """
                sources:
                  - id: toy_mass
                    value: 1.2
                    unit: GeV
                    source:
                      type: paper
                      arxiv: "0000.00000"
                """
            ),
        )
        report = check(folder, folder / "sources.yaml")
        self.assertEqual(len(report.failures), 1)
        self.assertEqual(report.failures[0].kind, "narration")
        self.assertIn("1.3", report.failures[0].value)
        self.assertEqual(len(report.matches), 1)

    def test_rounding_half_up_and_unit_conversion(self) -> None:
        folder = _deck(
            slide="Energy 13.6 TeV and a rounded toy 1.3.",
            narration="Nothing numeric here.",
            manifest=textwrap.dedent(
                """
                sources:
                  - id: toy_energy
                    value: 13600
                    unit: GeV
                    source:
                      type: paper
                      cds: CERN-EP-TOY-0001
                  - id: toy_rounded
                    value: 1.25
                    source:
                      type: paper
                      arxiv: "0000.00000"
                """
            ),
        )
        report = check(folder, folder / "sources.yaml")
        self.assertEqual(report.failures, [], _failures(report))
        ids = {item.source_id for item in report.matches}
        self.assertIn("toy_energy", ids)
        self.assertIn("toy_rounded", ids)

    def test_fit_file_disagrees_with_the_manifest(self) -> None:
        folder = _deck(
            slide="The toy mass is 1.2 GeV.",
            narration="The toy mass is one point two gigaelectronvolts.",
            manifest=textwrap.dedent(
                """
                sources:
                  - id: toy_mass
                    value: 1.2
                    unit: GeV
                    source:
                      type: fit_json
                      path: toy_fit.json
                      key: mass
                """
            ),
            fit='{"label": "TOY", "mass": 9.9}\n',
        )
        report = check(folder, folder / "sources.yaml")
        self.assertTrue(any("9.9" in error for error in report.source_errors))
        self.assertFalse(report.ok)

    def test_bad_hepdata_record_is_a_manifest_error(self) -> None:
        folder = _deck(
            slide="1.2",
            narration="one point two",
            manifest=textwrap.dedent(
                """
                sources:
                  - id: toy
                    value: 1.2
                    source:
                      type: hepdata
                      record: "not-a-record"
                """
            ),
        )
        with self.assertRaises(ManifestError):
            load_manifest(folder / "sources.yaml")

    def test_html_footer_page_number_is_exempt(self) -> None:
        html = """
        <div class="slide"><p>TOY mass 1.2 GeV.</p></div>
        <div class="global-footer"><span id="pageNumber">2 / 4</span></div>
        """
        document = load_document(_write(Path(tempfile.mkdtemp()) / "talk.html", html), "slide")[0]
        hits = extract_numbers(document)
        page_hits = [hit for hit in hits if "page_chrome" in hit.hints or "footer_page_mark" in hit.hints]
        self.assertTrue(page_hits)
        self.assertTrue(any(hit.value == Decimal("1.2") for hit in hits))


def _hits(text: str) -> list:
    document = Document("toy.txt", "narration", text, [Region(0, len(text), 1)])
    return extract_numbers(document)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _deck(
    *,
    slide: str,
    narration: str,
    manifest: str,
    fit: str | None = None,
) -> Path:
    folder = Path(tempfile.mkdtemp())
    _write(
        folder / "talk.html",
        f"<!DOCTYPE html><body><div class='slide'><p>{slide}</p></div></body>",
    )
    _write(folder / "narration.txt", narration + "\n")
    _write(folder / "sources.yaml", manifest)
    if fit is not None:
        _write(folder / "toy_fit.json", fit)
    return folder


def _failures(report) -> str:
    lines = [f"{item.kind} {item.value} {item.surface}" for item in report.failures]
    lines.extend(report.source_errors)
    return "\n".join(lines)


if __name__ == "__main__":
    unittest.main()
