#!/usr/bin/env python3
"""Slides + narration -> MP4. See video/README.md.

    python render-video.py video/examples/toy-peak -o /tmp/toy-peak.mp4
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from video.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
