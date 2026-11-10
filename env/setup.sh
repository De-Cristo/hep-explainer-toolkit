#!/usr/bin/env bash
# Create .venv with Python 3.12 and install env/requirements.txt.
# Safe to re-run. Does not call sudo.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv is not on PATH." >&2
  echo "Install uv from https://docs.astral.sh/uv/ and re-run env/setup.sh." >&2
  exit 1
fi

# `uv venv` exits with an error when .venv already exists. Reuse a 3.12
# environment; replace anything else.
if [[ -x .venv/bin/python ]] && .venv/bin/python -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)'; then
  uv venv --python 3.12 --allow-existing .venv
else
  uv venv --python 3.12 --clear .venv
fi

# The PyTorch CPU index also publishes old copies of packages that live on
# PyPI (certifi, tqdm, ...). uv's default strategy stops at the first index
# that has the project name, which rejects the pins in requirements.txt.
# unsafe-best-match is the same merge pip does with --extra-index-url.
uv pip install \
  --python .venv/bin/python \
  --index-strategy unsafe-best-match \
  -r env/requirements.txt

echo "Installed versions:"
.venv/bin/python - <<'PY'
import importlib.metadata as metadata
import en_core_web_sm

for dist in ("manim", "kokoro", "torch"):
    print(f"{dist} {metadata.version(dist)}")
print(f"en_core_web_sm {en_core_web_sm.__version__}")
PY

# MathTex/Tex need these. Manim Text does not. Warn only.
latex_missing=()
if ! command -v latex >/dev/null 2>&1; then
  latex_missing+=(latex)
fi
if ! command -v dvisvgm >/dev/null 2>&1; then
  latex_missing+=(dvisvgm)
fi
if ((${#latex_missing[@]} > 0)); then
  echo >&2
  echo "warning: missing on PATH: ${latex_missing[*]}" >&2
  echo "Manim MathTex and Tex need LaTeX. Manim Text works without it." >&2
  echo "This script does not use sudo. Recommended Debian/Ubuntu packages:" >&2
  echo "  sudo apt-get install -y texlive-latex-base texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended texlive-pictures texlive-science texlive-luatex dvisvgm cm-super poppler-utils" >&2
else
  echo "latex $(command -v latex)"
  echo "dvisvgm $(command -v dvisvgm)"
fi

missing=()
if ! command -v ffmpeg >/dev/null 2>&1; then
  missing+=(ffmpeg)
fi
if ! command -v espeak-ng >/dev/null 2>&1; then
  missing+=(espeak-ng)
fi
if ((${#missing[@]} > 0)); then
  echo >&2
  echo "Missing on PATH: ${missing[*]}" >&2
  echo "This script does not use sudo. Install the Debian/Ubuntu packages with:" >&2
  echo "  sudo apt-get install -y ffmpeg espeak-ng libcairo2-dev libpango1.0-dev pkg-config build-essential" >&2
  exit 1
fi

echo "ffmpeg $(command -v ffmpeg)"
echo "espeak-ng $(command -v espeak-ng)"
