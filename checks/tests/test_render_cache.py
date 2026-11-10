"""Render-cache integrity tests that run in the lightweight checks CI."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video.record import record_stills


class RenderCacheIntegrityTest(unittest.TestCase):
    def test_old_screenshot_is_removed_before_capture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            stale = work / "frame.png"
            stale.write_bytes(b"x" * 9001)

            def fake_run(plan, timeout):
                self.assertGreater(timeout, 0)
                self.assertFalse(stale.exists())
                stale.write_bytes(b"fresh")

                class Done:
                    stdout = ""

                return Done()

            with patch("video.record._require_playwright", lambda: None), patch(
                "video.record._run_node", fake_run
            ):
                record_stills(Path("deck.html"), [(1, 0, stale)], [1.0], work)

            self.assertEqual(stale.read_bytes(), b"fresh")


if __name__ == "__main__":
    unittest.main()
