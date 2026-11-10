# HEP visualization toolkit: inventory and integration map

Initial upstream survey: 2026-11-09. The repository now contains working HEP-specific checks, diagram rendering, scene rendering, and a narrated slide-video path; this file keeps the upstream integration survey but no longer treats the toolkit itself as untested.

## Current capability status

| Capability | Status | Entry point / example |
|---|---|---|
| Audience + learning-goal authoring brief | implemented + tested | `python3 -m checks.brief check examples/briefs/vhbb-undergraduate.yaml` |
| Citation / excerpt / equation checks | implemented + tested | `python3 -m checks.diagrams check SCENE.yaml` |
| SM UFO vertex + fermion-flow validation | implemented + tested | `checks/diagrams.py`, `examples/theory/vh/` |
| Number traceability | implemented + tested | `python3 -m checks.traceability check ...` |
| Confidentiality + provenance gate | implemented + tested | `python3 -m checks.confidentiality scan .` |
| Frontend slide deck -> narrated MP4 | implemented; Playwright/Kokoro runtime required | `python render-video.py video/examples/toy-peak` |
| Theory scene -> narrated MP4 | implemented; renderer dependencies required | `python3 -m video.explain SCENE.yaml -o build/out.mp4` |
| Static / animated Feynman diagrams | implemented | `python3 -m diagrams ...` |
| Semantic narration-to-visual cue timing | implemented + tested for theory diagram scenes | `checks/storyboard.py`, segmented narration in `video/explain.py` |
| Live-slide ↔ video semantic cue parity | implemented + tested | `slides/cues.py`, `data-scene` / `data-cue` |
| Reveal-state visual QA contact sheet | implemented; Playwright runtime required | `python -m video.qa DECK` |
| Environment capability doctor | implemented + tested | `python -m checks.doctor` |
| Reusable audience-independent scientific claim objects | implemented + tested | `checks/claims.py`, `examples/theory/vh/claims.yaml` |
| Definition comparison + assumption propagation | implemented + tested | `checks/claims.py` definitions, dependencies, comparisons |
| Hash-bound human interpretation review | implemented + tested | `python -m checks.review ...` |
| Privacy-aware local evidence | implemented + tested | `visibility: private`, local evidence bound to review digest |
| Bounded method-validation semantics | implemented + tested | storyboard `method_validation` block |
| Integrated scientific review/release packet | implemented + tested | `python -m checks.release ...` |
| Source-bound candidate authoring packs | implemented + tested | `python -m checks.authoring init/index/check` |
| Explicit candidate-to-claim promotion | implemented + tested | one-candidate `checks.authoring promote`, interpretation reset to pending |
| Approval-gated authoring handoff | implemented + tested | `checks.authoring handoff` JSON for downstream slide/video authoring |
| Multi-audience end-to-end benchmark | implemented + tested | `examples/vhbb/` public, student, and specialist variants |
| Synthetic scene render in CI | implemented + tested | `video/tests/test_explain_integration.py` |
| Publication packages for Indico/CDS/YouTube | planned | not yet implemented |

The sections below describe the upstream components and the original integration rationale. Items explicitly marked as guesses remain survey notes rather than supported toolkit features.

## 1. What we gathered
| Repo (commit) | Licence | What it is | Needs |
|---|---|---|---|
| ManimCommunity/manim (e80274a) | MIT | Python engine for scripted maths and physics animation | LaTeX, cairo, pango, ffmpeg; CPU is fine |
| ManimCommunity/manim-voiceover (3dc0d95) | MIT | Syncs Manim animations to narration with `with self.voiceover(text=...)`. Speech services: azure, elevenlabs, gemini, gtts, openai, pyttsx3, recorder. No Kokoro service | One of those speech services |
| motion-canvas (7b91435) | MIT | TypeScript animation with a timeline editor and a built-in ffmpeg exporter | Node |
| slidevjs/slidev (437f139) | MIT | Markdown slides with Vue and presenter recording | Node |
| De-Cristo/frontend-slides-PKU, branch feat/engine-updates-umd (5335c3f) | MIT | **Already a HEP skill** (`hep-frontend-slides.md`): fixed 1920×1080 canvas, 11 skins, step reveals, review comments, PDF export, `test-steps.mjs` (Playwright walks every step), plotlyhep as a submodule | Python, Node, Playwright |
| DickyChant/cms-plotting (75a342e) | MIT | Claude Code skill for CMS-style matplotlib/mplhep and Plotly canvases (fit+pulls, scans, toys, comparisons), `lint.py`, per-project `.claude/cms-plotting/` customization | matplotlib, mplhep, plotly |
| DickyChant/plotlyhep (49fe516) | BSD-3 | mplhep mirrored in Plotly, pixel-checked against mplhep | plotly |
| showlab/Paper2Video (47beb50) | MIT | LaTeX paper → Beamer slides → subtitles → F5-TTS voice clone (WhisperX alignment) → cursor → Hallo2 talking head → merge. Includes an evaluation suite (PresentQuiz, IP Memory) | GPT-4.1 or Gemini 2.5 Pro (or local Qwen); **48 GB GPU recommended** (A6000) for the full pipeline |
| showlab/Code2Video (1142d8e) | MIT | Planner, Coder and Critic agents writing Manim code, with a visual layout critic using anchors and icon assets. Evaluation scripts (aesthetics, TeachQuiz) | Manim 0.19; Claude works best for coding; IconFinder API for icons |
| TIGER-AI-Lab/TheoremExplainAgent (e9ece5d, last push Jul 2025) | MIT | Planner and code generator for long Manim theorem videos, a RAG over Manim docs, a renderer with error-fix loop, **Kokoro TTS via ONNX** | LiteLLM models; Kokoro ONNX model (CPU OK) |
| zhuyansen/awesome-claude-video-skills (366da94) | CC0 list | About 180 video skills. Closest to us: adithya-s-k/manim_skill (1.3k★), SunandBean/paper2video (Three.js + local Kokoro + ffmpeg, fact-checked), Science-Prof-Robot/recursive-math-animator (Manim + manim-voiceover), sepi2p/research-explainer-skill (claim checks, real-data figures; list flags it CAUTION), cymcymcymcym/notes-to-video | — |

## 2. What links directly (little or no new code)
1. **Plots → slides.** cms-plotting makes PNG/SVG for static use and Plotly JSON through plotlyhep. frontend-slides-PKU already ships plotlyhep as a submodule, so the two are designed to sit together.
2. **Slides → video.** `test-steps.mjs` already drives the deck step by step in headless Chromium at 1920×1080. Adding Playwright `recordVideo` (or a screenshot per step) gives the frames, and timing comes from the narration length per step (guess: about 50–100 lines of code).
3. **Narration.** Kokoro is used offline in TheoremExplainAgent (ONNX, CPU). Script per step → Kokoro WAV → duration → slide timing → SRT captions from the same text → ffmpeg mux with a `mov_text` track. ffmpeg is already on the box.
4. **Animations inside a talk.** Manim + manim-voiceover renders a clip (for example a Feynman diagram building up, or a decay length growing) as MP4/WebM, and the HTML slide embeds it as a `<video>` step.
5. **Agent loops.** Code2Video's Planner/Coder/Critic and TheoremExplainAgent's RAG + render-fix loop can be reused as they are for generating Manim scenes from a storyboard.

## 3. What must be adapted for HEP (the real gaps)
1. **A HEP visual asset library for Manim and HTML.** Feynman diagrams (TikZ-Feynman → SVG, or native Manim), CMS detector cross-section and layers, η–φ maps, jets and cones, vertices and decay lengths, pileup vertices along z, mass peaks and fits growing. None of the repos has these.
2. **A Kokoro service for manim-voiceover** (subclass `services/base.py`), so one offline voice works in both Manim clips and slide videos.
3. **A HEP pronunciation lexicon** for TTS: J/ψ, tt̄, fb⁻¹, GeV/TeV, σ, χ², "13.6 TeV", process names, CMS jargon. Generic TTS gets these wrong (guess, to be tested).
4. **CMS rules as checks, not prompts.** The label per stage (Private work, Work in progress, Preliminary, Simulation), the approval state of each number, and a confidentiality gate so internal plots never go into a public video. cms-plotting's `lint.py` covers plot style; extend it to the whole deck and video.
5. **A claim checker.** Every number spoken or shown must trace to a file such as a fit output or a datacard (the idea in sepi2p's skill and SunandBean's "fact-checked" pipeline).
6. **Paper2Video for CMS sources.** It takes LaTeX, which suits CMS PAS and AN in the TDR template (guess: needs a TDR-macro shim). Swap F5-TTS for Kokoro and drop Hallo2, which needs a large GPU; the box has none.
7. **Publication.** Exports for Indico, CDS and YouTube: chapters from slide titles, SRT, a thumbnail, and the CMS approval tag in metadata.
8. **Evaluation.** Adapt Paper2Video's PresentQuiz and Code2Video's TeachQuiz to "can a CMS colleague answer N questions about the analysis after watching".

## 4. Overlaps to settle
- **Slides:** frontend-slides-PKU vs Slidev. The first is HEP-ready and has step testing; Slidev has a bigger ecosystem. Proposal: frontend-slides-PKU as the primary, Slidev optional.
- **Animation:** Manim vs Motion Canvas. Manim has the AI agent ecosystem (Code2Video, TEA, many skills) and is Python like the analysis. Motion Canvas is better for hand-timed TypeScript scenes. Proposal: Manim as the primary.
- **End-to-end pipelines:** Paper2Video (from a paper) vs Code2Video/TEA (from a topic). Keep both as modes: "paper or AN → talk video" and "concept → explainer clip".

## 5. Proposed shape (guess, for discussion)
`hep-viz-toolkit/` with five parts, each also usable as an agent skill:
`plots/` (cms-plotting + plotlyhep) · `slides/` (frontend-slides-PKU) · `anim/` (Manim + HEP assets + Kokoro voiceover) · `video/` (step recorder + TTS + SRT + ffmpeg, plus Paper2Video mode) · `checks/` (CMS labels, confidentiality, claim checker, lint).
First milestone: rebuild one ~2-minute section of a deck as a narrated MP4 on CPU only. That tests links 1–3 end to end.
