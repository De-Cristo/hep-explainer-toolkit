"""Pure semantic states for resolved diagrams.

This module has no renderer or TTS dependencies so cue semantics can be
validated in the lightweight checks test suite.
"""

from __future__ import annotations


class DiagramStateError(ValueError):
    """A semantic cue references an invalid diagram state."""


def cue_drawing(drawing: dict, show_lines: object) -> dict:
    """Return a resolved diagram state containing only the requested lines."""
    if show_lines in (None, "all"):
        return {
            "vertices": drawing["vertices"],
            "lines": list(drawing["lines"]),
            "positions": drawing.get("positions") or {},
        }
    if not isinstance(show_lines, list):
        raise DiagramStateError(
            "show_lines must be a list of diagram line ids or 'all'"
        )
    wanted = {str(item) for item in show_lines}
    known = {str(line["id"]) for line in drawing["lines"]}
    unknown = sorted(wanted - known)
    if unknown:
        raise DiagramStateError(
            "unknown diagram line id(s): " + ", ".join(unknown)
        )
    return {
        "vertices": drawing["vertices"],
        "lines": [
            line for line in drawing["lines"]
            if str(line["id"]) in wanted
        ],
        "positions": drawing.get("positions") or {},
    }
