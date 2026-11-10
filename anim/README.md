# anim

Scripted clips inside a talk. Manim (`upstream/manim`) is the primary engine: it is Python, like the analysis code, and it is what Code2Video and TheoremExplainAgent already generate. Motion Canvas (`upstream/motion-canvas`) is optional, for scenes that are easier to time by hand in TypeScript.

Narration of a Manim scene goes through `upstream/manim-voiceover` (`with self.voiceover(text=...)`). Two HEP pieces are still missing from every upstream repo and will live here:

- A visual asset library: Feynman diagrams (TikZ-Feynman SVG, or native Manim), the CMS detector cross-section and layers, η–φ maps, jets and cones, vertices and decay lengths, pileup vertices along z, and mass peaks and fits growing.
- One offline voice for both Manim clips and slide videos: a Kokoro service subclassing manim-voiceover's `services/base.py`, plus a pronunciation lexicon so J/ψ, tt̄, fb⁻¹, GeV/TeV, σ, χ², "13.6 TeV", process names, and other CMS jargon are spoken correctly.

Rendered output under `media/`, and mp4, webm, wav, and mp3 files, are gitignored. Commit scene sources, not renders. Do not commit internal or unapproved CMS material.
