# video

The narrated film, and the publication package around it.

The direct path from a deck: `test-steps.mjs` already steps a frontend-slides deck in headless Chromium at 1920×1080. Playwright `recordVideo`, or a screenshot per step, supplies the frames. Timing comes from the narration length of each step (Kokoro ONNX, the offline voice TheoremExplainAgent uses, is the planned default and runs on CPU). The same script becomes SRT captions. ffmpeg muxes picture, audio, and a `mov_text` track. ffmpeg is the assembler; this folder holds the glue, not a second copy of the upstream engines.

Two source modes stay side by side. Paper or analysis note to a talk video follows the Paper2Video shape (LaTeX to slides to subtitles to voice), adapted to a CMS PAS or AN in the TDR template, with Kokoro instead of F5-TTS and without Hallo2. Concept to a short explainer follows Code2Video or TheoremExplainAgent and renders through `anim/`.

Publication exports for Indico, CDS, and YouTube: chapters taken from slide titles, the SRT, a thumbnail, and the CMS approval tag in metadata.

Rendered media (mp4, webm, wav, mp3) and model weights are gitignored. Inputs must be approved public results or toy and simulated examples. Do not commit internal videos.
