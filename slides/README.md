# slides

Talk decks. `upstream/frontend-slides-PKU` (branch `feat/engine-updates-umd`) is the primary engine: a fixed 1920×1080 canvas, eleven skins, step reveals, review comments, PDF export, and `test-steps.mjs`, which walks every step in headless Chromium. It is already a HEP slide skill and already expects plotlyhep figures.

`upstream/slidev` is the optional alternative (Markdown slides, Vue, presenter recording, a larger ecosystem). New decks should start on frontend-slides-PKU.

A deck consumes files from `plots/` and can embed a clip from `anim/` as a `<video>` step. `video/` records the same steps. The engines do not ship HEP drawings (detector views, Feynman diagrams, η–φ maps); those assets are an `anim/` gap, and static public figures come from `plots/`.

Only approved public results, or toy and simulated examples, belong here. Do not commit internal or unapproved CMS slides.

## Reviewed authoring scaffold

v0.4 can turn a current, human-approved authoring handoff into an editable frontend-slides starting point:

```bash
python -m checks.authoring verify-handoff build/approved-authoring.json

python -m slides.scaffold build/approved-authoring.json \
  --out-dir build/deck \
  --author "Name" \
  --event "Authoring review"
```

The default template is the pinned `upstream/frontend-slides-PKU/assets/templates/Empty_template.html`. The output includes `deck.html`, semantic `narration.yaml`, and `scaffold-plan.json`.

This is not an automatic final-talk generator. It preserves the approved scientific/reasoning structure and gives the authoring agent a real deck with the correct reveal-state/narration contract, while leaving clearly marked visual-intent placeholders for actual plots, diagrams, figures, or animation. The plan always records `release_ready: false`.

## Semantic cue parity

The pinned frontend engine already advances `.st[data-st=N]` fragments with ArrowRight/PageDown. v0.3 adds semantic names without changing that engine.

Mark a slide and its reveal elements:

```html
<section class="slide" data-scene="wh">
  <div class="st" data-st="1" data-cue="incoming">...</div>
  <div class="st" data-st="2" data-cue="complete">...</div>
</section>
```

A narration step may then use the semantic target instead of a numeric slide/step pair:

```yaml
steps:
  - scene: wh
    cue: incoming
    text: "The incoming quarks form an off-shell W."
```

`python -m slides.cues check SCENE.yaml DECK.html` validates that storyboard cues exist in the live deck and occur in presentation order. `python -m slides.cues manifest DECK.html` prints the semantic-to-numeric map. Numeric `slide:` / `step:` narration remains supported; if numeric and semantic fields are both present, they must agree.

## Visual QA

`python -m video.qa DECK --out build/deck-qa.html` captures every reveal state and writes a self-contained contact sheet. Browser capture waits for fonts, decoded images, MathJax, and an optional `window.hepContentReady` promise before declaring the deck ready. The QA report flags broken images and obvious element overflow. Use `--strict` to make those findings fail the command.
