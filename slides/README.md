# slides

Talk decks. `upstream/frontend-slides-PKU` (branch `feat/engine-updates-umd`) is the primary engine: a fixed 1920×1080 canvas, eleven skins, step reveals, review comments, PDF export, and `test-steps.mjs`, which walks every step in headless Chromium. It is already a HEP slide skill and already expects plotlyhep figures.

`upstream/slidev` is the optional alternative (Markdown slides, Vue, presenter recording, a larger ecosystem). New decks should start on frontend-slides-PKU.

A deck consumes files from `plots/` and can embed a clip from `anim/` as a `<video>` step. `video/` records the same steps. The engines do not ship HEP drawings (detector views, Feynman diagrams, η–φ maps); those assets are an `anim/` gap, and static public figures come from `plots/`.

Only approved public results, or toy and simulated examples, belong here. Do not commit internal or unapproved CMS slides.
