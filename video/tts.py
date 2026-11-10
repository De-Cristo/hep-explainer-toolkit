"""Kokoro ONNX, CPU only. Weights are downloaded on first use and never committed."""

from __future__ import annotations

import re
import urllib.request
from pathlib import Path

# model-files-v1.1 ships a duration head and a float speed input. int8 is the
# CPU default (about 114 MB). fp32 is the full graph (about 326 MB).
_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
MODELS = {
    "int8": f"{_RELEASE}/kokoro-v1.0.int8.onnx",
    "fp16": f"{_RELEASE}/kokoro-v1.0.fp16.onnx",
    "fp32": f"{_RELEASE}/kokoro-v1.0.onnx",
}
VOICES_URL = f"{_RELEASE}/voices-v1.0.bin"
_MIN_BYTES = {"int8": 50_000_000, "fp16": 80_000_000, "fp32": 200_000_000, "voices": 10_000_000}

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def cache_dir() -> Path:
    import os
    root = os.environ.get("HEP_KOKORO_CACHE")
    if root:
        path = Path(root)
    else:
        path = Path.home() / ".cache" / "hep-explainer-toolkit" / "kokoro"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _download(url: str, dest: Path, minimum: int) -> None:
    if dest.is_file() and dest.stat().st_size >= minimum:
        print(f"kokoro: using {dest} ({dest.stat().st_size / 1e6:.0f} MB)")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".partial")
    print(f"kokoro: downloading {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "hep-explainer-toolkit/0.1"})
    with urllib.request.urlopen(request, timeout=120) as response:
        total = int(response.headers.get("Content-Length") or 0)
        got = 0
        last = -1
        with partial.open("wb") as handle:
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                handle.write(chunk)
                got += len(chunk)
                if total:
                    pct = int(got * 20 / total)
                    if pct != last:
                        print(f"kokoro: {dest.name} {got / 1e6:.0f}/{total / 1e6:.0f} MB")
                        last = pct
    if partial.stat().st_size < minimum:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"download of {url} is only {got} bytes; expected at least {minimum}")
    partial.replace(dest)
    print(f"kokoro: saved {dest}")


def ensure_weights(precision: str, model: Path | None, voices: Path | None) -> tuple[Path, Path]:
    if precision not in MODELS:
        raise ValueError(f"unknown precision {precision!r}; choose from {', '.join(MODELS)}")
    if model is None:
        name = Path(MODELS[precision]).name
        model = cache_dir() / name
        _download(MODELS[precision], model, _MIN_BYTES[precision])
    elif not model.is_file():
        raise FileNotFoundError(model)
    if voices is None:
        voices = cache_dir() / "voices-v1.0.bin"
        _download(VOICES_URL, voices, _MIN_BYTES["voices"])
    elif not voices.is_file():
        raise FileNotFoundError(voices)
    return model, voices


def _split_for_tts(text: str, limit: int = 280) -> list[str]:
    """Kokoro rejects a chunk past its phoneme limit. Break on sentences first."""
    sentences = [part.strip() for part in _SENTENCE.split(text.strip()) if part.strip()]
    if not sentences:
        return []
    chunks: list[str] = []
    buf = ""
    for sentence in sentences:
        if len(sentence) > limit:
            if buf:
                chunks.append(buf)
                buf = ""
            words = sentence.split()
            piece = ""
            for word in words:
                trial = word if not piece else f"{piece} {word}"
                if len(trial) > limit and piece:
                    chunks.append(piece)
                    piece = word
                else:
                    piece = trial
            if piece:
                chunks.append(piece)
            continue
        trial = sentence if not buf else f"{buf} {sentence}"
        if len(trial) > limit and buf:
            chunks.append(buf)
            buf = sentence
        else:
            buf = trial
    if buf:
        chunks.append(buf)
    return chunks


class KokoroSpeaker:
    def __init__(self, model: Path, voices: Path, threads: int, lang: str, speed: float, voice: str):
        # Imported here so lexicon and deck tests do not load onnxruntime.
        import numpy as np
        import onnxruntime as ort
        from kokoro_onnx import Kokoro

        self._np = np
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        session = ort.InferenceSession(
            str(model),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        # from_session reads this; InferenceSession does not set it itself.
        session._model_path = str(model)
        self.kokoro = Kokoro.from_session(session, str(voices))
        self.lang = lang
        self.speed = speed
        self.voice = voice
        self.sample_rate = 24000

    def phonemes(self, text: str) -> str:
        try:
            return str(self.kokoro.tokenizer.phonemize(text, lang=self.lang))
        except TypeError:
            return str(self.kokoro.tokenizer.phonemize(text))
        except Exception as exc:  # phoneme log is diagnostic, not the product
            return f"(phonemize failed: {exc})"

    def write(self, text: str, dest: Path) -> float:
        import soundfile as sf

        chunks = _split_for_tts(text)
        if not chunks:
            raise ValueError("nothing to synthesize")
        pieces = []
        rate = self.sample_rate
        gap = int(0.12 * rate)
        silence = self._np.zeros(gap, dtype=self._np.float32)
        for index, chunk in enumerate(chunks):
            samples, rate = self.kokoro.create(
                chunk,
                voice=self.voice,
                speed=self.speed,
                lang=self.lang,
            )
            samples = self._np.asarray(samples, dtype=self._np.float32)
            if samples.size == 0:
                raise RuntimeError(f"Kokoro returned no audio for: {chunk}")
            if index:
                pieces.append(silence)
            pieces.append(samples)
        audio = self._np.concatenate(pieces)
        self.sample_rate = int(rate)
        dest.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(dest), audio, self.sample_rate)
        return float(audio.shape[0]) / float(self.sample_rate)


def wav_duration(path: Path) -> float:
    import soundfile as sf

    info = sf.info(str(path))
    if info.samplerate <= 0 or info.frames <= 0:
        raise RuntimeError(f"{path} has no audio frames")
    return info.frames / float(info.samplerate)
