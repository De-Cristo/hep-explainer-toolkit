"""Kokoro speech on CPU. Weights and the spaCy model are downloaded at runtime."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# misaki's English G2P loads this by name. The 3.8.0 wheel matches spaCy 3.8.x,
# which is what kokoro 0.9.4 pulls in. Do not commit the wheel or the weights.
SPACY_MODEL = "en_core_web_sm"
SPACY_MODEL_WHEEL = (
    "https://github.com/explosion/spacy-models/releases/download/"
    "en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
)
SAMPLE_RATE = 24000
_LANG = {"en-us": "a", "en-gb": "b", "a": "a", "b": "b"}


def ensure_spacy_model() -> str:
    """Install ``en_core_web_sm`` if misaki would otherwise download it itself.

    Kokoro's English frontend calls ``spacy.load("en_core_web_sm")`` the first
    time a pipeline is built. A missing model used to fail the render, or
    depend on misaki's own ``spacy.cli.download`` with no record of the pin.
    """
    try:
        import spacy
    except ImportError as exc:
        raise SystemExit(
            "spaCy is not installed. Kokoro's English phonemizer needs it, "
            "and the model en_core_web_sm. Install env/requirements.in with Python 3.12."
        ) from exc
    if spacy.util.is_package(SPACY_MODEL):
        print(f"kokoro: spaCy model {SPACY_MODEL} is installed")
        return SPACY_MODEL

    version = tuple(int(part) for part in spacy.__version__.split(".")[:2])
    if version == (3, 8):
        print(f"kokoro: downloading {SPACY_MODEL} ({SPACY_MODEL_WHEEL})")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", SPACY_MODEL_WHEEL],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
    else:
        print(
            f"kokoro: spaCy {spacy.__version__} is not 3.8; "
            f"downloading a compatible {SPACY_MODEL} via spaCy"
        )
        from spacy.cli import download
        download(SPACY_MODEL)
    if not spacy.util.is_package(SPACY_MODEL):
        raise SystemExit(
            f"{SPACY_MODEL} is still missing. Install it with:\n"
            f"  pip install '{SPACY_MODEL_WHEEL}'"
        )
    print(f"kokoro: installed {SPACY_MODEL}")
    return SPACY_MODEL


class KokoroSpeaker:
    """hexgrad's ``kokoro`` package, forced onto the CPU torch wheel."""

    def __init__(self, threads: int, lang: str, speed: float, voice: str):
        import torch
        from kokoro import KPipeline

        if getattr(torch.version, "cuda", None):
            raise SystemExit(
                f"torch {torch.__version__} is a CUDA build. Install the CPU wheel:\n"
                "  pip install torch==2.15.0+cpu --index-url https://download.pytorch.org/whl/cpu"
            )
        torch.set_num_threads(threads)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass  # a previous call in this process already started the pool

        code = _LANG.get(lang)
        if code is None:
            raise SystemExit(f"unsupported narration lang {lang!r}; use en-us or en-gb")
        ensure_spacy_model()
        # repo_id avoids the library's "defaulting repo_id" warning. Weights
        # download into the Hugging Face cache on first use (~/.cache/huggingface).
        self.pipeline = KPipeline(lang_code=code, repo_id="hexgrad/Kokoro-82M", device="cpu")
        self.speed = speed
        self.voice = voice
        self.last_phonemes = ""

    def write(self, text: str, dest: Path) -> float:
        import numpy as np
        import soundfile as sf

        pieces: list[np.ndarray] = []
        phonemes: list[str] = []
        for result in self.pipeline(text, voice=self.voice, speed=self.speed):
            audio = result.audio
            if audio is None:
                continue
            samples = audio.detach().cpu().float().numpy().reshape(-1)
            if samples.size:
                pieces.append(samples)
            if result.phonemes:
                phonemes.append(result.phonemes)
        if not pieces:
            raise RuntimeError(f"Kokoro returned no audio for: {text}")
        wave = np.concatenate(pieces).astype(np.float32, copy=False)
        self.last_phonemes = " ".join(phonemes)
        dest.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(dest), wave, SAMPLE_RATE)
        return float(wave.shape[0]) / float(SAMPLE_RATE)


def wav_duration(path: Path) -> float:
    import soundfile as sf

    info = sf.info(str(path))
    if info.samplerate <= 0 or info.frames <= 0:
        raise RuntimeError(f"{path} has no audio frames")
    return info.frames / float(info.samplerate)
