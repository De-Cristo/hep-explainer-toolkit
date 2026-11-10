"""Keep numeric libraries and ffmpeg inside a CPU thread budget."""

from __future__ import annotations

import os

_KEYS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMBA_NUM_THREADS",
)


def apply_thread_limit(threads: int) -> None:
    """Force the process-wide thread cap. Call before importing onnxruntime."""
    if threads < 1:
        raise ValueError(f"threads must be >= 1, got {threads}")
    value = str(threads)
    for key in _KEYS:
        os.environ[key] = value
    os.environ["HEP_VIDEO_THREADS"] = value
