# Environment setup

Python 3.12 environment for rendering and narration. `env/setup.sh` creates `.venv` and installs the lock in `env/requirements.txt`. Model weights stay out of git.

Confirmed on Debian 13, x86_64, CPU only (no GPU), with CPython 3.12.15.

## System packages

Debian and Ubuntu names:

```bash
sudo apt-get install -y ffmpeg espeak-ng libcairo2-dev libpango1.0-dev pkg-config build-essential
```

| Package | Role |
| --- | --- |
| `ffmpeg` | Manim writes video through ffmpeg. |
| `espeak-ng` | Kokoro / misaki English phonemization. |
| `libcairo2-dev`, `libpango1.0-dev`, `pkg-config`, `build-essential` | `pycairo` 1.29.2 and `manimpango` 0.7.1 have no Linux wheels at these pins, so pip builds them. |
| Python headers | `pycairo`'s build looks up a `python` pkg-config module. A [uv-managed CPython](https://docs.astral.sh/uv/concepts/python-versions/) ships the headers. A distro CPython needs `python3.12-dev` as well. |

`env/setup.sh` checks that `ffmpeg` and `espeak-ng` are on `PATH`. It does not run `sudo`. If either command is missing it prints the `apt-get` line above and exits non-zero after the virtualenv install. A missing `latex` or `dvisvgm` prints a warning and the script still succeeds.

Node.js 20 or newer is required for the slide engine and Playwright. The tested version is Node 20.19.2. `env/setup.sh` does not install Node. Distro `nodejs` packages are often older than 20, so install Node 20+ from Node's own distribution or a version manager.

### LaTeX

LaTeX is recommended for animations. Manim `MathTex` and `Tex` fail without it, and HEP narration slides need math such as μ, fb⁻¹, and J/ψ. Manim `Text` uses Pango and works without LaTeX.

These Debian/Ubuntu package names were checked against the archive. `texlive-latex-base` pulls in `texlive-binaries`, which provides the `latex` command. `texlive-latex-extra` depends on `texlive-latex-recommended`, which includes amsmath. `dvisvgm` is the converter Manim uses for math scenes. `cm-super` supplies Type 1 Computer Modern fonts so the glyphs are not bitmaps.

```bash
sudo apt-get install -y texlive-latex-base texlive-latex-extra texlive-fonts-recommended dvisvgm cm-super
```

`env/setup.sh` warns when `latex` or `dvisvgm` is missing and does not fail the run.

### Versions confirmed on Debian 13

| Component | Version |
| --- | --- |
| ffmpeg | 7.1.5 |
| espeak-ng | 1.52.0 |
| cairo | 1.18.4 |
| pango | 1.56.3 |
| Node.js | 20.19.2 |
| Python | 3.12.15 |

## Python packages

Direct dependencies are declared in `env/requirements.in`. `env/requirements.txt` is the full pin set for CPython 3.12, resolved for x86_64 `manylinux_2_28` and constrained to the confirmed freeze.

| Package | Pin |
| --- | --- |
| kokoro | 0.9.4 |
| misaki | 0.9.4 |
| manim | 0.22.1 |
| manimpango | 0.7.1 (via manim) |
| pycairo | 1.29.2 (via manim) |
| matplotlib | 3.11.2 |
| mplhep | 1.3.3 |
| numpy | 2.5.4 |
| soundfile | 0.14.0 |
| pyyaml | 6.0.3 |
| torch | 2.15.0+cpu |
| en_core_web_sm | 3.8.0, GitHub wheel URL in the lock (spaCy `>=3.8.0,<3.9.0`, matches spaCy 3.8.18) |
| manim-voiceover | 0.4.0 in the lock; unpinned in `requirements.in` |
| uproot | 5.7.7 in the lock; unpinned in `requirements.in` |

`manim-voiceover` was not part of the confirmed install and is untested. The lock picked 0.4.0, which also pulls the PyPI `sox` package (a wrapper around the SoX binary). That binary is not in the apt line above. Importing `sox` while the binary is absent prints `SoX could not be found`. Install the distro `sox` package before trying voiceover. `uproot` is there to read ROOT files from public HEPData or CERN Open Data.

kokoro 0.9.4 requires Python `>=3.10,<3.13`. Use 3.12.

## uv quick start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then from the repository root:

```bash
./env/setup.sh
source .venv/bin/activate
```

The script is safe to run again. It runs `uv venv --python 3.12` (reusing an existing 3.12 `.venv`, replacing any other interpreter) and installs `env/requirements.txt` with uv. A re-run prints the installed `manim`, `kokoro`, and `torch` versions and imports `en_core_web_sm`.

uv will download a CPython 3.12 build if the machine does not already have one. Prefer that managed interpreter: it includes the headers `pycairo` needs. If `uv venv --python 3.12` selects a distro interpreter and the `pycairo` build then fails, see Troubleshooting.

## CPU-only torch

The confirmed freeze recorded `torch==2.15.0`. That install was the CUDA wheel `2.15.0+cu132` (about 514 MB) plus the `nvidia-*`, `cuda-*`, and `triton` packages. On a CPU-only machine those files only take disk.

The CPU wheel exists on the official CPU index. Checked for this lock:

`https://download.pytorch.org/whl/cpu/torch-2.15.0+cpu-cp312-cp312-manylinux_2_28_x86_64.whl` (209530490 bytes, about 200 MB).

`env/requirements.txt` pins `torch==2.15.0+cpu` and points uv/pip at that index:

```text
--extra-index-url https://download.pytorch.org/whl/cpu
```

The same index still hosts old copies of unrelated projects (`certifi`, `tqdm`, and others). uv's default index strategy uses only the first index that publishes a given name, so a plain `uv pip install -r env/requirements.txt` cannot see the newer PyPI pins. `env/setup.sh` passes `--index-strategy unsafe-best-match`, which considers every configured index. That is the merge pip already does for `--extra-index-url`. Both indexes here are the upstream ones (PyPI and `download.pytorch.org`).

## Model weights

Kokoro downloads its checkpoint and voice files on first use through `huggingface_hub`, from `hexgrad/Kokoro-82M` (`config.json`, `kokoro-v1_0.pth`, and `voices/<name>.pt`). They land in the Hugging Face cache, usually `~/.cache/huggingface`, which is outside this repository. Do not copy them into the tree. Do not commit them.

Kokoro and misaki also need spaCy's English model `en_core_web_sm` at runtime. That model is not a Hugging Face download. `env/requirements.txt` pins the 3.8.0 wheel from the spaCy models GitHub release, the same URL and sha256 as the confirmed freeze, which matches the locked spaCy 3.8.18 (`>=3.8.0,<3.9.0`). `env/setup.sh` imports `en_core_web_sm` after install. The wheel is installed inside `.venv`. Do not commit it.

`.gitignore` ignores `.venv/`. The virtualenv is local state.

## Troubleshooting

### pycairo says `Python dependency not found`

The build cannot see Python headers. Use a uv-managed interpreter, which includes them:

```bash
uv python install 3.12
uv venv --python 3.12 --managed-python --clear .venv
uv pip install --python .venv/bin/python --index-strategy unsafe-best-match -r env/requirements.txt
```

Or install the distro headers and the Cairo/Pango build dependencies:

```bash
sudo apt-get install -y python3.12-dev libcairo2-dev libpango1.0-dev pkg-config build-essential
```

### kokoro on Python 3.13 resolves to 0.7.x

kokoro 0.8 and later, including 0.9.4, require `>=3.10,<3.13`. On 3.13 a resolver can only select the 0.7 line (`0.7.9` allows `>=3.7`). Create the environment with Python 3.12 (`uv venv --python 3.12`).
