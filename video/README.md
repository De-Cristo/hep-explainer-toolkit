# video

The narrated film, and the publication package around it.

The direct path from a deck: `test-steps.mjs` in `upstream/frontend-slides-PKU` already steps a frontend-slides deck in headless Chromium at 1920×1080. This folder is the v0.1 glue from that walk to an MP4: a narration file, Kokoro speech, one settled frame per step, SRT captions, and ffmpeg. It does not copy the slide engine and it does not modify the submodule. The recorder repeats the `test-steps.mjs` contract (spoof `navigator.webdriver`, 1920×1080, one ArrowRight per reveal) because that script has no exports.

A theory scene, rather than a slide deck, is a second entry point. It reuses Kokoro, the SRT writer, and ffmpeg. Each scene contributes one picture: a diagram still, a Manim clip, an equation slide, a figure, or a plot. `video.mux.fit_segment` holds a still for the narration and freezes the last frame of a short clip so the picture lasts as long as the audio (the failure mode where a 20 s drawing sat under 44 s of speech).

```bash
python3 -m video.explain examples/theory/vh/scene.yaml -o build/vh.mp4
```

The scene format and the rules for picking a still versus a clip are in [AGENTS.md](../AGENTS.md). `python render-video.py` is unchanged and still renders a frontend-slides deck.

Rendered media (mp4, webm, wav, mp3) and model weights are gitignored. Inputs must be approved public results or toy and simulated examples. Do not commit internal videos.

## v0.1 command

From the repo root, with Python 3.12:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r env/requirements.in
npm --prefix video install
npx --prefix video playwright install chromium
# if Chromium will not start, the machine is missing system libraries:
#   sudo npx --prefix video playwright install-deps chromium

python render-video.py video/examples/toy-peak -o /tmp/toy-peak.mp4
```

`env/requirements.in` is the Python 3.12 list for this path (Kokoro, misaki, CPU torch, and spaCy's `en_core_web_sm`). A separate setup change owns the wider pin; keep these lines when the files are combined. Torch must be the CPU wheel (`torch==2.15.0+cpu` from the PyTorch CPU index). The PyPI file with the same version number is the CUDA build.

`video/examples/toy-peak` is a three-slide deck scaffolded from the slide engine. Every number on it is made up and labelled toy / simulated. The command writes the MP4, a sibling `.srt`, and a `.timings.json`. Default output, if you omit `-o`, is `<deck>/build/<name>.mp4`, which is gitignored.

Check the script against the deck, and print the text Kokoro will see, without downloading weights:

```bash
python render-video.py video/examples/toy-peak --check
```

| Flag | Meaning |
|---|---|
| `-o, --out` | Output MP4 |
| `-n, --narration` | Narration file, if the deck was passed as an HTML path rather than a folder |
| `--burn-in` | Also draw captions in a bottom band. Off by default: the file carries a soft `mov_text` track, so axis labels stay visible |
| `--subtitle-band N` | Height of that burned-in strip, in pixels on the 1080-tall frame. Default **180** |
| `--threads N` | CPU cap for torch and ffmpeg. Default **4**. Also sets `OMP_NUM_THREADS` and the usual BLAS variables |
| `--pad SECONDS` | Silence after each step. Overrides `pad_seconds` in the narration file |
| `--voice` | Kokoro voice. Default `af_sarah` |
| `--speed` | 0.5 to 2.0 |
| `--capture auto\|video\|stills` | `auto` tries Playwright `recordVideo`, then per-step screenshots if the browser dies or the picture drifts from the audio. Default **auto** |
| `--work-dir` | Keep the PNGs and WAVs |
| `--check` | Validate only |

`python -m video` is the same entry point.

Kokoro 0.9 downloads `hexgrad/Kokoro-82M` on first use (checkpoint and voice) into the Hugging Face cache, usually `~/.cache/huggingface`. Nothing in that cache is committed.

Kokoro's English phonemizer is misaki, and misaki loads spaCy's `en_core_web_sm` at runtime. `render-video` installs it if it is missing: the pinned wheel is `en_core_web_sm` 3.8.0, which matches spaCy 3.8.x. On another spaCy minor version it uses `python -m spacy download en_core_web_sm`. The model lives in the virtualenv. Do not commit it.

### Dependencies

Python 3.12, from `env/requirements.in`:

- `kokoro==0.9.4` and `misaki==0.9.4`, on CPU (`KPipeline(..., device="cpu")`)
- `torch==2.15.0+cpu` from `https://download.pytorch.org/whl/cpu`. A `+cu` build is refused
- `en-core-web-sm` 3.8.0 (the runtime spaCy model above)
- `soundfile`, `numpy`, `pyyaml`
- `pytest` to run the tests

Node, from `video/package.json`:

- `playwright`, plus the Chromium browser it downloads

System:

- `ffmpeg` / `ffprobe` with libx264, AAC, the `subtitles` filter (libass), and `mov_text`
- `espeak-ng` for the phonemizer's out-of-dictionary fallback (`espeakng-loader` ships a library; a system `espeak-ng` is what the setup notes install)

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

Each step's on-screen hold is the measured WAV duration plus the pad. The pipeline then checks that the finished file's video stream, audio stream, and that timeline agree within **0.2s**, and exits if they do not.

Playwright opens the deck at 1920×1080 in **Playwright's own Chromium** (`chromium.executablePath()`, not `/usr/bin/google-chrome`), hides the PDF-export shortcut (`navigator.webdriver`), and presses ArrowRight once per step — the same key `test-steps.mjs` uses. `--capture auto` (the default) tries `recordVideo` once, sleeping for each measured hold. Playwright only finalizes that webm when the browser context is closed, including from a `finally` block and from SIGTERM. A 0-byte webm, a killed browser, a timeout, or a picture that misses the audio by more than 0.2s falls back to one PNG per step and ffmpeg holds each PNG for that step's audio duration. The screenshot walk retries after a dead browser instead of aborting the deck. `--capture stills` skips `recordVideo`. `--capture video` does not fall back.

ffmpeg then builds H.264 + AAC. The SRT is a `mov_text` track (`-c:s mov_text`). That is the default, so captions stay in the player and off the plot. `--burn-in` also paints them in a black strip at the bottom of the frame (`--subtitle-band`, default 180px on a 1080-tall canvas) so they do not cover axis labels.

### Tests

```bash
pytest video/tests -q
```

`test_pipeline.py` uses a generated tone instead of Kokoro and checks that video, audio, and the timeline match within 0.2s, that a `mov_text` track is present, and that burn-in darkens only the bottom band. `test_smoke.py` runs real Kokoro. Set `HEP_SKIP_SMOKE=1` to skip that download.

### Known gaps

- `recordVideo` is attempted, and a drifted or aborted take is replaced by stills. The stills path does not play the engine's 0.45s fade.
- Captions are one cue per step, not word-timed. Burn-in covers the bottom band (default 180px) so it does not share pixels with axis labels; a plot drawn in that strip is hidden behind the band.
- The lexicon is a rewrite list. It does not know every CMS acronym. The words "eta" and "phi" are left as written: espeak already says /ˈiːtə/ and /faɪ/. The symbols η and φ are mapped to those words. χ² is rewritten, because the raw symbol comes out as "chai two".
- The phonemizer sometimes glues a function word to the next one ("has not" shows up as one token). The waveform still says the phrase; the phoneme string in `.timings.json` is the place you will see it.
- English (`en-us`) only. The voice default is `af_sarah`.
- MathJax and webfonts on a real deck are waited on for a few seconds, then the frame is taken anyway. The toy deck has those CDN tags removed so it renders offline.
- No Manim, no paper-to-video mode, no claim checker, no CMS approval label, no Indico / CDS / YouTube package. Those stay in `anim/`, `checks/`, and the notes above.
