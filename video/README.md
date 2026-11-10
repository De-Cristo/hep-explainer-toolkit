# video

The narrated film, and the publication package around it.

The direct path from a deck: `test-steps.mjs` in `upstream/frontend-slides-PKU` already steps a frontend-slides deck in headless Chromium at 1920×1080. This folder is the v0.1 glue from that walk to an MP4: a narration file, Kokoro speech, one settled frame per step, SRT captions, and ffmpeg. It does not copy the slide engine and it does not modify the submodule. The recorder repeats the `test-steps.mjs` contract (spoof `navigator.webdriver`, 1920×1080, one ArrowRight per reveal) because that script has no exports.

Two later modes stay out of this version. Paper or analysis note to a talk video follows the Paper2Video shape. Concept to a short explainer follows Code2Video or TheoremExplainAgent and renders through `anim/`. Neither is wired here, and Manim is not a dependency of this path.

Rendered media (mp4, webm, wav, mp3) and model weights are gitignored. Inputs must be approved public results or toy and simulated examples. Do not commit internal videos.

## v0.1 command

From the repo root, with Python 3.12:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r video/requirements.txt
npm --prefix video install
npx --prefix video playwright install chromium
# if Chromium will not start, the machine is missing system libraries:
#   sudo npx --prefix video playwright install-deps chromium

python render-video.py video/examples/toy-peak -o /tmp/toy-peak.mp4
```

`video/examples/toy-peak` is a three-slide deck scaffolded from the slide engine. Every number on it is made up and labelled toy / simulated. The command writes the MP4, a sibling `.srt`, and a `.timings.json`. Default output, if you omit `-o`, is `<deck>/build/<name>.mp4`, which is gitignored.

Check the script against the deck, and print the text Kokoro will see, without downloading weights:

```bash
python render-video.py video/examples/toy-peak --check
```

| Flag | Meaning |
|---|---|
| `-o, --out` | Output MP4 |
| `-n, --narration` | Narration file, if the deck was passed as an HTML path rather than a folder |
| `--burn-in` | Draw captions on the picture. A `mov_text` track is embedded either way |
| `--threads N` | CPU cap for Kokoro (ONNX intra-op) and ffmpeg. Default **4**. Also sets `OMP_NUM_THREADS` and the usual BLAS variables |
| `--pad SECONDS` | Silence after each step. Overrides `pad_seconds` in the narration file |
| `--voice` | Kokoro voice. Default `af_sarah` |
| `--speed` | 0.5 to 2.0 |
| `--precision int8\|fp16\|fp32` | Graph to download. **int8** is the CPU default (~114 MB). `fp32` is the full graph (~326 MB) |
| `--model`, `--voices` | Use files you already have, instead of downloading |
| `--work-dir` | Keep the PNGs and WAVs |
| `--check` | Validate only |

`python -m video` is the same entry point.

Kokoro weights land in `~/.cache/hep-explainer-toolkit/kokoro/` (override with `HEP_KOKORO_CACHE`). They are fetched from the `kokoro-onnx` `model-files-v1.1` release the first time you render. Nothing in that cache is committed.

### Dependencies

Python 3.12, from `video/requirements.txt`:

- `kokoro-onnx` (ONNX Runtime, CPU provider only — the session is created with `CPUExecutionProvider`)
- `soundfile`, `numpy`, `PyYAML`
- `pytest` to run the tests

Node, from `video/package.json`:

- `playwright`, plus the Chromium browser it downloads

System:

- `ffmpeg` / `ffprobe` with libx264, AAC, the `subtitles` filter (libass), and `mov_text`
- `espeak-ng` data is bundled by `kokoro-onnx` (`espeakng-loader`); a system espeak is not required

Another change is adding `SETUP.md` and an `env/` pin. This folder does not own those files. Use Python 3.12 however that environment is set up.

### Narration file

`narration.yaml` beside `deck.html`. One block per reveal state, in the order ArrowRight walks the deck:

```yaml
title: A toy mass peak
voice: af_sarah
lang: en-us
speed: 1.0
pad_seconds: 0.35
steps:
  - slide: 1          # 1-based, the <!-- [Slide N] --> index
    step: 0           # arrival, before any class="st" fragment
    text: >
      This toy talk is simulated.
  - slide: 2
    step: 1           # the ArrowRight that reveals data-st="1"
    text: >
      A toy Gaussian appears, centred near 125 GeV.
```

Step 0 is the slide as it arrives. If the highest `data-st` on a slide is 2, that slide needs steps 0, 1, and 2. The pipeline refuses a missing cue, an extra cue, or a file that is not in presentation order.

Captions use `text` as written. `video/lexicon/hep.yaml` rewrites a copy of that string before TTS, so `J/psi`, `ttbar`, `fb^-1`, `GeV` / `TeV`, `13.6 TeV`, `chi-squared`, `H->bb`, `ZH` / `WH`, `p_T`, `eta` / `phi`, and `σ η φ` are spoken as words. The longest match at each character wins, so `13.6 TeV` does not get rewritten a second time by the bare `TeV` rule. Point `lexicon:` in the narration file at another YAML to replace the list; paths are relative to the narration file.

### What the recorder does

Playwright opens the deck at 1920×1080, hides the PDF-export shortcut (`navigator.webdriver`), and presses ArrowRight once per step — the same key `test-steps.mjs` uses. Each PNG is the settled frame. The engine's 0.45s opacity fade is disabled for the capture, and ffmpeg holds the PNG for the WAV length plus the pad. That keeps the MP4 duration equal to the sum of the holds. A `recordVideo` webm would include the fade, and its clock would be the wall clock of the browser rather than the audio.

ffmpeg then builds H.264 + AAC. The SRT is a `mov_text` track (`-c:s mov_text`). `--burn-in` also draws it.

### Tests

```bash
pytest video/tests -q
```

`test_pipeline.py` uses a generated tone instead of Kokoro and checks that the MP4 duration matches the timeline and that a `mov_text` track is present. `test_smoke.py` runs the real int8 model. Set `HEP_SKIP_SMOKE=1` to skip that download.

### Known gaps

- Still frames, not the CSS fade. A later cut could record the transition with `recordVideo` if the fade matters more than an exact hold.
- Captions are one cue per step, not word-timed.
- The lexicon is a rewrite list. It does not know every CMS acronym, and int8 is a quantized graph (spectral correlation about 0.92 against fp32, per the kokoro-onnx release notes). Use `--precision fp32` when the voice matters more than the download. The words "eta" and "phi" are left as written: espeak already says /ˈiːtə/ and /faɪ/, and rewriting them made the vowels worse. The symbols η and φ are mapped to those words. χ² is rewritten, because the raw symbol comes out as "chai two".
- The phonemizer sometimes glues a function word to the next one ("has not" shows up as one token). The waveform still says the phrase; the phoneme string in `.timings.json` is the place you will see it.
- English (`en-us`) only. The voice default is `af_sarah`.
- MathJax and webfonts on a real deck are waited on for a few seconds, then the frame is taken anyway. The toy deck has those CDN tags removed so it renders offline.
- No Manim, no paper-to-video mode, no claim checker, no CMS approval label, no Indico / CDS / YouTube package. Those stay in `anim/`, `checks/`, and the notes above.
