"""Confidentiality gate: toy fixtures only, no real CMS material."""

from __future__ import annotations

import base64
import io
import struct
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout
from pathlib import Path

import hashlib

from checks.confidentiality import load_config, main, scan
from checks.pdftext import extract_pdf_text
from examples.toy.emit import toy_png

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _png(comment: str) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    text = b"Comment\x00" + comment.encode("utf-8")
    raw = zlib.compress(b"\x00\xff\x00\x00")

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    return signature + chunk(b"IHDR", ihdr) + chunk(b"tEXt", text) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


class ConfidentialityFixtureTest(unittest.TestCase):
    def test_public_toy_deck_passes(self) -> None:
        report = scan(FIXTURES / "confidentiality_pass")
        self.assertEqual(report.failures, [], format_findings(report.failures))
        self.assertEqual(report.warnings, [], format_findings(report.warnings))

    def test_internal_markers_fail(self) -> None:
        report = scan(FIXTURES / "confidentiality_fail")
        rules = {item.rule_id for item in report.failures}
        self.assertIn("cms_private_work", rules)
        self.assertIn("cms_internal", rules)
        self.assertIn("analysis_note", rules)
        self.assertIn("detector_note", rules)
        self.assertIn("cadi_line", rules)
        self.assertIn("twiki_viewauth", rules)
        self.assertIn("twiki_cms_web", rules)
        self.assertIn("cms_cern_ch", rules)
        self.assertIn("cms_docdb", rules)
        self.assertIn("indico_private", rules)
        channels = {item.channel for item in report.failures if item.rule_id == "cms_private_work"}
        self.assertIn("filename", channels)
        self.assertIn("pdf", channels)
        self.assertIn("html-text", channels)
        # A public-looking arXiv id in the same file does not clear a CADI code.
        cadi = [item for item in report.failures if item.rule_id == "cadi_line"]
        self.assertTrue(cadi)
        self.assertTrue(all(item.severity == "fail" for item in cadi))

    def test_preliminary_is_only_a_warning(self) -> None:
        folder = FIXTURES / "confidentiality_preliminary"
        report = scan(folder)
        self.assertEqual(report.failures, [])
        self.assertTrue(report.warnings)
        self.assertTrue(all(item.rule_id == "preliminary" for item in report.warnings))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["scan", str(folder)]), 0)

    def test_work_in_progress_fails_until_explicitly_allowed(self) -> None:
        blocked = scan(FIXTURES / "confidentiality_wip")
        self.assertTrue(any(item.rule_id == "work_in_progress" for item in blocked.failures))
        allowed = scan(FIXTURES / "confidentiality_wip_allowed")
        self.assertEqual(allowed.failures, [], format_findings(allowed.failures))
        exemptions = [item for item in allowed.findings if item.rule_id == "work_in_progress"]
        self.assertTrue(exemptions)
        self.assertTrue(all(item.severity == "exempt" for item in exemptions))
        self.assertIn("explicitly allowed", exemptions[0].note)

    def test_cadi_allow_file_records_the_reference(self) -> None:
        report = scan(FIXTURES / "confidentiality_cadi_allowed")
        self.assertEqual(report.failures, [])
        cleared = [item for item in report.findings if item.rule_id == "cadi_line"]
        self.assertTrue(cleared)
        self.assertIn("arXiv:0000.00000", cleared[0].note)

    def test_cli_fail_exit(self) -> None:
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["scan", str(FIXTURES / "confidentiality_fail")]), 1)

    def test_repo_itself_has_no_failures(self) -> None:
        report = scan(ROOT)
        self.assertEqual(report.failures, [], format_findings(report.failures))

    def test_unlisted_png_is_refused_without_a_marker(self) -> None:
        """An internal-looking plot with no marker word and no manifest row is blocked."""
        png = toy_png()
        digest = hashlib.sha256(png).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "toy_plot.png").write_bytes(png)
            (folder / "internal_plot.png").write_bytes(_png("mass distribution"))
            (folder / "sources.yaml").write_text(
                "files:\n"
                "  - path: toy_plot.png\n"
                "    source:\n"
                "      type: toy\n"
                "      generator: examples/toy/emit.py\n"
                f"      sha256: {digest}\n",
                encoding="utf-8",
            )
            report = scan(folder)
        undeclared = [item for item in report.failures if item.rule_id == "undeclared"]
        self.assertEqual(
            [item.path for item in undeclared],
            ["internal_plot.png"],
            format_findings(report.failures),
        )
        self.assertTrue(all(item.rule_id != "cms_private_work" for item in report.failures))

    def test_bare_toy_label_is_refused(self) -> None:
        png = toy_png()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "toy_plot.png").write_bytes(png)
            (folder / "sources.yaml").write_text(
                "files:\n  - path: toy_plot.png\n    source: toy\n",
                encoding="utf-8",
            )
            report = scan(folder)
        self.assertTrue(any(item.rule_id == "toy_provenance" for item in report.failures))

    def test_toy_generator_hash_must_match_a_rerun(self) -> None:
        png = toy_png()
        digest = hashlib.sha256(png).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "toy_plot.png").write_bytes(png)
            (folder / "sources.yaml").write_text(
                "files:\n"
                "  - path: toy_plot.png\n"
                "    source:\n"
                "      type: toy\n"
                "      generator: examples/toy/emit.py\n"
                f"      sha256: {digest}\n",
                encoding="utf-8",
            )
            clean = scan(folder)
            self.assertEqual(clean.failures, [], format_findings(clean.failures))
            (folder / "sources.yaml").write_text(
                "files:\n"
                "  - path: toy_plot.png\n"
                "    source:\n"
                "      type: toy\n"
                "      generator: examples/toy/emit.py\n"
                f"      sha256: {'0' * 64}\n",
                encoding="utf-8",
            )
            mismatch = scan(folder)
        self.assertTrue(any(item.rule_id == "toy_provenance" for item in mismatch.failures))


class ConfidentialityUnitTest(unittest.TestCase):
    def test_jpeg_comment(self) -> None:
        comment = b"TOY CMS Internal"
        blob = b"\xff\xd8\xff\xfe" + struct.pack(">H", len(comment) + 2) + comment + b"\xff\xd9"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "toy.jpg"
            path.write_bytes(blob)
            report = scan(path)
        self.assertTrue(
            any(item.channel == "jpeg:COM" and item.rule_id == "cms_internal" for item in report.failures)
        )

    def test_png_metadata_and_data_uri(self) -> None:
        blob = _png("TOY CMS Private Work")
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "toy.png").write_bytes(blob)
            encoded = base64.b64encode(blob).decode("ascii")
            (folder / "deck.html").write_text(
                f'<img alt="toy plot" src="data:image/png;base64,{encoded}">\n',
                encoding="utf-8",
            )
            report = scan(folder)
        channels = {item.channel for item in report.failures if item.rule_id == "cms_private_work"}
        self.assertIn("png:tEXt:Comment", channels)
        self.assertTrue(any(channel.startswith("embedded-png:tEXt") for channel in channels))

    def test_flate_pdf_text(self) -> None:
        payload = zlib.compress(b"BT (TOY CMS Internal) Tj ET")
        pdf = (
            b"%PDF-1.4\n1 0 obj\n<< /Length "
            + str(len(payload)).encode("ascii")
            + b" /Filter /FlateDecode >>\nstream\n"
            + payload
            + b"\nendstream\nendobj\ntrailer << >>\n%%EOF\n"
        )
        self.assertIn("CMS Internal", extract_pdf_text(pdf))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "toy.pdf"
            path.write_bytes(pdf)
            report = scan(path)
        self.assertTrue(any(item.rule_id == "cms_internal" for item in report.failures))

    def test_config_marks_wip_allowable_and_preliminary_as_warning(self) -> None:
        config = load_config()
        by_id = {rule.id: rule for rule in config.rules}
        self.assertTrue(by_id["work_in_progress"].allowable)
        self.assertEqual(by_id["work_in_progress"].severity, "fail")
        self.assertEqual(by_id["preliminary"].severity, "warn")
        self.assertFalse(by_id["cms_private_work"].allowable)


def format_findings(findings: list) -> str:
    return "\n".join(
        f"{item.severity} {item.rule_id} {item.path} [{item.channel}] {item.snippet}"
        for item in findings
    )


if __name__ == "__main__":
    unittest.main()
