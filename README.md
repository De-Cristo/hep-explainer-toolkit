# HEP explainer toolkit

Environment setup for Python 3.12: [SETUP.md](SETUP.md).

How an agent should choose a figure, a diagram, an animation, slides, or a narrated video, and which checks are mandatory: [AGENTS.md](AGENTS.md).

Turn public high-energy physics results into professional slides, animations, short clear narrated explainer videos, and publication-ready exports. The pieces are upstream tools linked as git submodules. This repository is the HEP-specific layer on top of them: what to run, in which order, and which physics rules the output has to satisfy.

For a new explanation, start with an audience/learning-goal brief before writing slides or narration. `python3 -m checks.brief check BRIEF.yaml` validates that the audience, prerequisites, concepts to introduce, purpose, medium, and learning goal are explicit. See `examples/briefs/vhbb-undergraduate.yaml` and [AGENTS.md](AGENTS.md).

Renderers now declare an explicit render job: every slide, narration file, scene, visual asset, evidence file, and source manifest has a role. Validation follows those exact inputs rather than guessing from filenames, and the render seal includes the manifests plus local fit/datacard evidence. See `checks/renderjob.py`.

Reusable scientific content can live in a project-local `claims.yaml`. Scenes reference stable claim IDs while keeping audience-specific wording local; `python3 -m checks.claims check CLAIMS.yaml --report build/claim-review.md` produces a review surface with separate source, evidence, value, and interpretation states.

In v0.3, definition claims can declare dependencies and assumption tags, and `comparisons:` can state which registered claims support conditions under which two definitions agree or differ. Human interpretation approval is kept separate from machine checks: `python -m checks.review init claims.yaml reviews.json`, followed by explicit `approve` actions. Approvals are hash-bound to the claim, evidence excerpt, and upstream dependencies, so edits make them stale automatically.

For protected work, a claim registry may declare `visibility: private` and cite `citation.local: ../path/to/private-source`. Local evidence is rejected in a public registry, its excerpt must occur in the referenced local file, and the local source bytes are part of the human-review digest. `python -m checks.release SCENE --reviews REVIEWS --out build/review.html` builds an integrated private review packet. `--public` refuses private registries and additionally runs the renderer-equivalent public checks before reporting public-release readiness.


v0.4 adds a staged authoring workflow before the claim registry and an approval-gated handoff after it. `python -m checks.authoring init SOURCE --out candidates.yaml ...` binds a candidate pack to exact source bytes; candidates must quote that source and are not canonical science. `promote` moves exactly one explicitly selected candidate into `claims.yaml`, writes its evidence excerpt, and always sets interpretation to `pending`. `handoff` writes a machine-readable authoring plan only when every claim actually used by the storyboard has a current human approval. The handoff contains reviewed canonical statements, assumptions, caveats, audience wording, and visual intent, but not raw evidence excerpts.

The same release adds a dependency-free local review UI: `python -m checks.review_ui claims.yaml --reviews reviews.json --scene scene.yaml --reviewer "Name"`. It displays canonical statements beside exact evidence excerpts, inherited assumptions, caveats, dependencies, audience wording, and definition comparisons, with explicit Approve / Reject actions. Private registries are hard-limited to loopback; the page loads no external assets, uses no-store/CSP headers, and requires a per-session CSRF token for every decision.

Audience-specific scene files can also link to a validated brief and declare a reasoning sequence. `python3 -m checks.storyboard check SCENE.yaml --report build/storyboard-review.md` checks prerequisites, introduced concepts, required distinctions, claim references, and semantic visual cues. For theory diagrams, segmented narration cues now drive progressive line reveals in the narrated video.

`examples/vhbb/` is the first complete audience benchmark: public, undergraduate, and HEP-specialist explanations share reviewed scientific claims but use different reasoning paths. `python -m checks.explanation SCENE.yaml` runs the renderer-equivalent validation path without producing media.


v0.3 also adds output parity and machine readiness checks. Live decks can bind storyboard cue names to frontend-slides reveal steps with `data-scene` / `data-cue`; semantic narration resolves those names to the recorder's numeric states. `python -m video.qa DECK` builds a reveal-state contact sheet, and `python -m checks.doctor` reports which local capabilities are ready before a build starts.

Development assistance and attribution are recorded in [CONTRIBUTORS.md](CONTRIBUTORS.md).

> **This repository is public.** Never commit internal or unapproved CMS material. That includes plots, numbers, slides, and videos. The only figures, values, decks, and clips that may be added are approved public results, or toy and simulated examples. If a file is not clearly public, leave it out.

The project's own licence has not been chosen yet. There is no `LICENSE` file in this repository until the owner picks one. Each upstream project keeps the licence noted below; those licences do not licence this repository.

## Pipeline

```
plots → slides → animations → narration/subtitles → video → export
```

1. **Plots.** [cms-plotting](https://github.com/DickyChant/cms-plotting) writes static PNG and SVG (matplotlib / mplhep: fits with pulls, scans, toys, comparisons). [plotlyhep](https://github.com/DickyChant/plotlyhep) writes the matching Plotly JSON. See `plots/`.
2. **Slides.** [frontend-slides-PKU](https://github.com/De-Cristo/frontend-slides-PKU) is the primary deck (fixed 1920×1080 canvas, step reveals, PDF export). [Slidev](https://github.com/slidevjs/slidev) is optional. See `slides/`.
3. **Animations.** [Manim](https://github.com/ManimCommunity/manim) is the primary engine for clips embedded in a deck (a Feynman diagram building up, a decay length growing). [Motion Canvas](https://github.com/motion-canvas/motion-canvas) is optional for hand-timed TypeScript scenes. See `anim/`.
4. **Narration and subtitles.** A script per step becomes speech, the clip length sets the slide timing, and the same text becomes SRT captions. [manim-voiceover](https://github.com/ManimCommunity/manim-voiceover) already syncs Manim scenes. The planned shared offline voice is Kokoro, as used by [TheoremExplainAgent](https://github.com/TIGER-AI-Lab/TheoremExplainAgent).
5. **Video.** Playwright walks the deck step by step (`test-steps.mjs` in frontend-slides-PKU) and records frames. ffmpeg muxes picture, audio, and a `mov_text` caption track. A second mode follows [Paper2Video](https://github.com/showlab/Paper2Video) from a LaTeX note, and [Code2Video](https://github.com/showlab/Code2Video) from a topic. See `video/`.
6. **Export.** Packages for Indico, CDS, and YouTube: chapters from slide titles, SRT, a thumbnail, and the CMS approval tag in metadata. `checks/` has to pass before a public export.

The first milestone is one section of about two minutes, rebuilt as a narrated MP4 on CPU only. That exercises plots, slides, narration, and video together.

v0.1 of the slides → narrated MP4 path is `python render-video.py` (a deck folder plus a per-step narration file). It uses Kokoro on CPU and does not use Manim. See [video/README.md](video/README.md).

What already links, and what still has to be adapted for HEP (asset library, Kokoro service, pronunciation lexicon, CMS checks, claim checker, TDR papers, publication metadata, evaluation), is written up in [INVENTORY.md](INVENTORY.md).

## Layout

| Path | What lives there |
|---|---|
| `plots/` | CMS-style figures from cms-plotting and plotlyhep |
| `slides/` | Decks; frontend-slides-PKU primary, Slidev optional |
| `anim/` | Manim scenes, the HEP asset library, Kokoro voiceover |
| `video/` | Step recording, TTS, SRT, ffmpeg, and the paper-to-video mode |
| `checks/` | CMS labels, confidentiality, claim checks, lint |
| `upstream/` | The upstream repositories as git submodules, pinned, not copied |
| `INVENTORY.md` | Survey of what links directly and what must be adapted for HEP |

Upstream source stays in the submodules. Do not vendor it into this tree.

## Fetch the submodules

After a clone:

```bash
git submodule update --init
```

Or clone everything in one step:

```bash
git clone --recurse-submodules https://github.com/De-Cristo/hep-explainer-toolkit.git
```

`git submodule update --init` checks out the commit recorded for each submodule in this repository. Those pins are the survey commits from 2026-11-09 (full SHAs below). `upstream/frontend-slides-PKU` is the one submodule that tracks a branch: `feat/engine-updates-umd`. To move that submodule to the current tip of its branch and then review the result:

```bash
git submodule update --remote upstream/frontend-slides-PKU
```

The other submodules have no branch set, so a plain `git submodule update --init` stays on the pinned commit.

## Upstream licences

Recorded 2026-11-09. Each licence is the upstream project's own. This repository does not grant those licences, and it does not yet have a licence of its own.

| Submodule | Upstream | Branch | Pinned commit | Licence |
|---|---|---|---|---|
| `upstream/Code2Video` | [showlab/Code2Video](https://github.com/showlab/Code2Video) | `main` | `1142d8e14cdc2806df85aedb0fbb5dca474caa0f` | MIT License |
| `upstream/Paper2Video` | [showlab/Paper2Video](https://github.com/showlab/Paper2Video) | `main` | `47beb503e24218f8f8b3075f5d2bed7844d199b4` | MIT License |
| `upstream/TheoremExplainAgent` | [TIGER-AI-Lab/TheoremExplainAgent](https://github.com/TIGER-AI-Lab/TheoremExplainAgent) | `main` | `e9ece5db7756b6ded8a812eceeb936cfd02aae21` | MIT License |
| `upstream/awesome-claude-video-skills` | [zhuyansen/awesome-claude-video-skills](https://github.com/zhuyansen/awesome-claude-video-skills) | `main` | `366da94c737a0517856017b1248109e02622ac18` | CC0 1.0 Universal |
| `upstream/cms-plotting` | [DickyChant/cms-plotting](https://github.com/DickyChant/cms-plotting) | `main` | `75a342efcd0beb30a33bb27f6e640278ca50f788` | MIT License |
| `upstream/frontend-slides-PKU` | [De-Cristo/frontend-slides-PKU](https://github.com/De-Cristo/frontend-slides-PKU) | `feat/engine-updates-umd` | `5335c3f47169cd311a81bb6161f65d8069d656c1` | MIT License |
| `upstream/hep-skills` | [De-Cristo/hep-skills](https://github.com/De-Cristo/hep-skills) | `main` | `1c1800886839b3800d64fc7593b0f4023db5fdb1` | Apache License 2.0 |
| `upstream/manim-voiceover` | [ManimCommunity/manim-voiceover](https://github.com/ManimCommunity/manim-voiceover) | `main` | `3dc0d95d2f1d9d0937872b3dd68c7b38c4dfc96a` | MIT License |
| `upstream/manim` | [ManimCommunity/manim](https://github.com/ManimCommunity/manim) | `main` | `e80274a2586c3c2f8d72600fe873e5f7971c0c9c` | MIT License |
| `upstream/motion-canvas` | [motion-canvas/motion-canvas](https://github.com/motion-canvas/motion-canvas) | `main` | `7b91435c301d530351dcf5ebb91dd139c002e405` | MIT License |
| `upstream/plotlyhep` | [DickyChant/plotlyhep](https://github.com/DickyChant/plotlyhep) | `main` | `49fe516c52590b45d041f0bd2d57e2ec15d5b27f` | BSD 3-Clause License |
| `upstream/slidev` | [slidevjs/slidev](https://github.com/slidevjs/slidev) | `main` | `437f139ccd4c8482a193b217922e7800a5b3baec` | MIT License |

`awesome-claude-video-skills` is a CC0 list of other people's video skills, not a single library. `frontend-slides-PKU` describes itself as a HEP slide skill and already points at plotlyhep. `hep-skills` is the language-skill suite (presentation craft, text review, web report), pinned at the commit above and not copied into this tree. Read each upstream `LICENSE` before redistributing that submodule's code.
