# Agent instructions

This repository is public. Use public sources only: arXiv, a DOI, or a textbook those papers cite. Do not add CMS-internal material, and do not call a paid LLM API. The person already has an agent. This file says which command to run.

Plots and slides are optional. A theory explanation does not need a CMS plot.

## 0. Write the authoring brief first

For a new explanation, do not begin with narration or slide layout. First write a brief that makes the pedagogical choices explicit: the audience, what they already know, what must be introduced, the communication purpose, the medium, the learning goal, and scientific distinctions that must survive simplification.

Validate it before authoring:

```bash
python3 -m checks.brief check examples/briefs/vhbb-undergraduate.yaml
```

A minimal brief looks like:

```yaml
topic: "Why use associated production to study H to bb?"
audience:
  profile: physics_undergraduate
  knows:
    - particle_decay
  introduce:
    - jets
    - flavour_tagging
purpose: explain_analysis_strategy
medium: slides
duration_minutes: 5
learning_goal: "Explain how accompanying particles help identify a Higgs candidate."
required_distinctions:
  - "A bottom quark and a reconstructed b-tagged jet are different objects."
```

The audience profile is descriptive, not a fixed enum. A public explanation, a student explanation, and an analysis-approval talk should normally start from different questions and use different prerequisite chains. Do not create an audience variant by merely replacing technical words with simpler words. Rebuild the reasoning path from the brief.

The brief is an authoring input, not rendered scientific evidence. Claims, equations, numbers, diagrams, citations, provenance, and confidentiality still use the checks below.

## 1. Pick the output

Read the request and pick the smallest thing that answers it.

| The request needs | `visual.kind` | Command |
|---|---|---|
| One static picture of a formula or a layout | `slide` or `figure` | `python3 -m diagrams equation '...' -o out.png`, or point `visual.file` at an existing image |
| A Feynman diagram as a figure | `diagram` with `motion: still` | `python3 -m diagrams figure DIAGRAM.yaml -o out.png --svg out.svg` |
| The same diagram moving | `manim` or `diagram` with `motion: build` | `python3 -m diagrams animate DIAGRAM.yaml -o build/clip.mp4` |
| A deck of existing slides, narrated | the deck pipeline, not a scene file | `python3 render-video.py DECK/` |
| A short narrated film made of any mix of the above | a scene file | `python3 -m video.explain SCENE.yaml -o build/name.mp4` |
| A web blog or web report | not a slide deck | Follow [hep-web-report](upstream/hep-skills/skills/hep-web-report/SKILL.md). It does not replace a figure, a deck, or a narrated video. |

Use a plot (`visual.kind: plot`, or `plots/`) only when the request is about a measured or toy distribution. Do not invent one for a theory explanation.

`video.explain` holds each still for the length of its narration and, if a Manim clip is shorter than the narration, freezes the last frame until the audio ends. Do not ship a clip whose picture and sound differ by more than 0.2 s.

## 1.5. Put reusable science in a claim registry

When more than one explanation may reuse the same scientific content, keep the stable content in a project-local `claims.yaml` and let scenes reference it by id. The registry owns the canonical scientific statement, citation, excerpt, context, assumptions, caveats, and review state.

Validate it with:

```bash
python3 -m checks.claims check PATH/claims.yaml --report build/claim-review.md
```

Use `--strict` only for a release gate. Structural validation can pass while `interpretation: pending`; strict mode does not. This distinction is deliberate: declaring a source, storing evidence, matching a value, and reviewing an interpretation are different states.

A registry entry can look like:

```yaml
claims:
  - id: vh.wh.production
    kind: claim
    origin: theory
    statement: "Canonical scientific statement."
    citation:
      arxiv: "hep-ph/0503172"
      doi: "10.1016/j.physrep.2007.10.004"
      locator: "Sections 1 and 3"
    excerpt: excerpts/vh-wh.yaml
    context:
      model: SM
      process: WH
    assumptions:
      - "Tree-level explanatory topology."
    caveats:
      - "Generic q labels suppress flavour-mixing details."
    review:
      source: declared
      evidence: retrieved
      value: not_applicable
      interpretation: pending
```

A scene then keeps only its audience-specific wording and the stable reference:

```yaml
claim_registry: claims.yaml
scenes:
  - id: wh
    narration: "Audience-specific wording."
    visual:
      kind: diagram
      diagram: wh.yaml
    claims:
      - id: words
        claim_ref: vh.wh.production
        text: "Audience-specific wording."
```

Do not duplicate `citation:` or `excerpt:` next to a `claim_ref`; the registry is the source of truth. The checker shows the canonical statement beside the audience wording and evidence, but it does not claim to prove semantic equivalence. A human must review simplifications and interpretation.

## 1.55. Track definitions, assumptions, and human interpretation review

A quantity that has multiple legitimate definitions must not be represented as one ambiguous prose claim. Use `kind: definition` for each definition. A claim may declare `depends_on:` and `assumption_tags:`; the registry reports the transitive assumptions inherited from upstream claims.

When two definitions are compared, use a top-level `comparisons:` block whose `same_when` and `differs_when` entries reference supported claims. Do not put unsupported comparison prose directly in that block.

Machine readiness is not human interpretation approval. Create a separate review file:

```bash
python3 -m checks.review init PATH/claims.yaml PATH/reviews.json
python3 -m checks.review approve PATH/claims.yaml PATH/reviews.json CLAIM_ID --reviewer "Name"
python3 -m checks.review check PATH/claims.yaml PATH/reviews.json --strict
```

The approval digest includes the claim, its evidence excerpt, and upstream dependency digests. If any of them changes, the approval becomes `stale`. Never regenerate or approve a review file automatically as part of a release build; approval is an explicit human action.

## 1.6. Make the reasoning path and visual timing explicit

For an audience-specific explanation, connect the scene file to its brief with `brief:`. Each scene records the question it answers, the idea to retain, prerequisites, concepts introduced, the purpose of the visual, and why the next scene follows. Validate that chain before rendering:

```bash
python3 -m checks.storyboard check PATH/scene.yaml --report build/storyboard-review.md
```

Narration may remain one string for backward compatibility. When visual timing matters, split it into named segments and map each segment to a visual cue:

```yaml
brief: brief.yaml
scenes:
  - id: wh
    question: "What changes for charged-current WH production?"
    takeaway: "The initial W vertex changes quark flavour."
    requires:
      - quarks
    introduces:
      - associated_production
    visual_purpose: "Reveal the incoming state before the full topology."
    why_next: "Compare with neutral-current ZH."
    narration:
      - cue: incoming
        text: "A quark and antiquark form an off-shell W."
      - cue: complete
        text: "The full WH topology is then shown."
    visual:
      kind: diagram
      diagram: wh.yaml
      cues:
        - id: incoming
          show_lines:
            - q_in
            - qbar_in
            - wstar
        - id: complete
          show_lines: all
```

For diagram scenes, these cues are executable: each narration segment gets its own measured audio duration and the renderer draws exactly the named diagram lines for that interval. A cue with `show_lines: all` restores the complete diagram. Segmented diagram cues use progressive still states; an uncued `motion: build` scene continues to use the existing Manim path.

The storyboard checker also verifies that required concepts are known before use, all concepts requested by the brief are introduced, required distinctions are covered, claim references exist, narration cues have matching visual cues, and referenced diagram line IDs exist. These structural checks do not prove pedagogical quality; review the generated storyboard report.

## 2. Scene file

One YAML file. The checks parser does not accept anchors or `|` / `>` block scalars. Quote strings that contain a colon, and put TeX in single quotes so backslashes stay literal.

```yaml
title: "Name"
scenes:
  - id: wh
    narration: "Sentences that will be spoken."
    visual:
      kind: diagram          # slide | manim | diagram | figure | plot
      motion: still          # still | build
      diagram: wh.yaml       # diagram and manim
      # file: out/plot.png   # figure and plot
      # equations:           # slide
      #   - id: potential
      #     tex: 'V(\phi)=...'
    claims:
      - id: words
        kind: claim          # claim | equation | diagram
        text: "The narration, copied exactly."
        citation:
          arxiv: "0901.0241" # or hep-ph/0503172, or a doi
          locator: "eq15"   # must contain a number
        excerpt: excerpts/potential.yaml
```

A diagram file lists `positions`, `vertices` (`id` plus `particles`), and `lines` (`particle`, `source`, `target`). Leave `arrow` unset. The helper sets it. `source` to `target` is the momentum direction.

## 3. Diagram rules

Fermion arrows follow fermion number, not momentum. A particle arrow points with the momentum. An antiparticle arrow points against it. `python3 -m diagrams` reads that from the resolved spec. TikZ-Feynman then uses `fermion` or `anti fermion` along the momentum. Do not draw both arrows the way the line runs.

`q` and `qbar` are the same flavour. `q` and `qbar'` are different flavours. `W` means either charge. `W*` is an off-shell `W`.

Which vertices exist is not a table in the checker. It is the FeynRules Standard Model UFO shipped in MadGraph5_aMC@NLO `models/sm`, vendored at `checks/models/sm-ufo/`.

- Upstream: <https://github.com/mg5amcnlo/mg5amcnlo>
- Commit: `a5b17913ef0b6e1c872016f94d0fb610207dab47`
- Licence: `checks/models/sm-ufo/LICENSE`
- Pin: `checks/models/sm-ufo/SHA256SUMS`

`checks.ufo_model` loads `particles.py` and `vertices.py` and rejects a file whose digest does not match. A vertex is allowed only when some assignment of the labels is one of those UFO vertices or its conjugate. Charge and flavour fall out of that. In this model a `W` couples an up-type quark to a down-type quark, a `Z` or photon vertex is flavour-diagonal, and the photon has no neutrino vertex. Details are in `checks/models/PROVENANCE.md`.

## 4. Citations

Every narration, equation, and diagram in the scene needs a claim. The claim needs an arXiv id or a DOI, a locator with a number, and an excerpt file stored in the repo.

The excerpt's arXiv id or DOI and its locator must be the same as the claim. An equation has to appear in the excerpt quote. A diagram's vertex list has to match the excerpt's `vertices:` list. Neither of those is the physics check. The physics check is the UFO. A citation whose excerpt was copied from a wrong diagram still fails.

## 5. Language skills, and the order of checks

Narration, slide text, and an optional web report follow the language skills in the `upstream/hep-skills` submodule (Apache-2.0, pinned at `1c1800886839b3800d64fc7593b0f4023db5fdb1`, not copied). Read the skill file. Do not paste it into this repository.

The language and style pass happens first. Number trace, provenance, and the citation and diagram checks run only after that, and only on the narration and slide files that will be rendered. They never run on a pre-rewrite draft.

The renderers enforce this through `checks.renderjob.RenderJob`. They declare the role of every input instead of asking checkers to infer roles from filenames. The deck renderer parses narration once, then passes that same cue text to number traceability, captions, and TTS. The scene renderer does the same for scene narration. The seal covers render inputs, `sources.yaml`, and local fit/datacard evidence read by the number checker. If any sealed byte changes after validation, rendering stops.

Slide and narration inputs always require a public provenance declaration. Visual assets used directly by a scene do too. Metadata such as an in-repository scene spec or excerpt is validated by its dedicated checks; if such a file is supplied from outside the project root, it also requires explicit provenance. Moving a file or renaming it must never weaken a check.

Do the same by hand when you are not using that command: finish the two language skills, write the polished files, then run the checks on those paths. Do not check a draft and render a rewrite.

- Narration scripts and slide text follow [hep-presentation-craft](upstream/hep-skills/skills/hep-presentation-craft/SKILL.md).
- Every narration, caption, and slide text gets a [hep-text-review](upstream/hep-skills/skills/hep-text-review/SKILL.md) pass before any check and before rendering.
- A web blog or web report follows [hep-web-report](upstream/hep-skills/skills/hep-web-report/SKILL.md). The same order applies: polish the page, then run the checks on the file you will publish.

The machine half of the style pass is:

```bash
python3 -m checks.language scan PATH
```

Exit 1 means a banned phrase or a bullet over the word cap. A narration sentence over the cap is a warning, and a failure with `--strict`. The phrase list and the caps live in `checks/config/language.yaml`. The pipeline runs this before provenance and number trace. You do not have to run it twice.

### hep-presentation-craft

Slides and the words spoken over them. The procedure is the skill file. In short:

- The title is a physical conclusion with an active verb, not a topic name.
- One dominant visual, about 60–70% of the slide, plus two or three short bullets and one bottom-line sentence.
- ASD-STE100: at most 20 words on a bullet and 25 in a descriptive sentence, at most three nouns in a row, one meaning per word, active voice, no filler, no double negatives.
- The bullet cap is checked by `checks.language`. Noun stacks, assertion titles, and the bottom line are not. Those stay a reading of the skill.

### hep-text-review

Do this before any other check and before rendering narration, captions, or slide text. The procedure is the skill file. In short:

- Ground the numbers. A figure that is not in a local artifact, a paper, or a DOI is unverified. Do not invent one. This repository traces numbers with `checks.traceability` and refuses unapproved inputs with `checks.confidentiality`. The skill's tier list and citation roles are stricter than those checks, and they are not reimplemented here.
- Give each citation an explicit role. A generic citation is not enough when a primary definition exists.
- One name for one thing. Sentences in the 10–30 word range. Active voice. Delete throat-clearing and the AI filler in Flavor D.
- The filler phrases that are a fixed string are in `checks/config/language.yaml` and fail the lint. Voice, citation role, and whether a source actually supports the sentence are a reading of the skill, then the side-by-side citation report.

### hep-web-report

Use this when the request is a web blog or a web report, not a talk. The procedure is the skill file. In short:

- Open with a Start Here section a reader can finish in about a minute: what is true now, what has to be true next, the obstacle in one sentence, a diagram from the detector to the electronics, and one analogy.
- Group a long list of functions or registers into three or four clusters before the detailed tables. Register tables need a plain-language column.
- The same controlled English as the presentation skill, including the approved-word substitutions. The unambiguous substitutions are in the language lint. "Since" versus "because", imperative steps, and double negatives are not, because a machine cannot tell them apart from ordinary prose.
- A published page is one self-contained HTML file (theme, mathematics, diagrams). This repository does not ship that compiler. Follow the recipe in the skill when you build the page.

## 6. Before you finish

From the repository root, language first, then the checks on those same files:

```bash
python3 -m checks.explanation PATH/scene.yaml
python3 -m checks.language scan PATH
python3 -m checks.diagrams check PATH/scene.yaml
python3 -m checks.confidentiality scan .
python3 -m checks.traceability check PATH --manifest sources.yaml
python3 -m unittest discover -s checks/tests -t . -v
pytest video/tests -q -m "not smoke"
```

`render-video.py` and `python3 -m video.explain` run that order themselves and refuse to render if the narration or slide hash changed after the checks. `checks.diagrams check` prints a side-by-side of each item and the excerpt it cites. Read it. Exit 0 is not a substitute for that reading when the claim is prose: the quote is stored and shown, and a person decides whether the sentence follows.

Images, SVG, and narration files need a `sources.yaml` next to them (`files:` with `source.type` of `arxiv`, `hepdata`, `cds`, or a toy generator). The provenance rule accepts a new-style arXiv id (`NNNN.NNNNN`) only. An old id such as `hep-ph/0503172` is fine inside a scene citation and is not accepted as the `files:` source type. Commit PNG and SVG. Leave MP4, WAV, and Manim `media/` out of git. Write videos under `build/`.

If the scene speaks a number, the traceability check still applies, on the polished narration and slides.

## 7. Examples

- `examples/theory/vh/` — `q qbar' → W* → WH`, `H → b bbar`, and `q qbar → Z* → ZH`. Stills are in `out/`. The narrated film is built, not committed.
- `examples/theory/higgs/` — the potential, the vacuum value, and `M_H = \sqrt{2\lambda}\,\nu`, quoted from arXiv:0901.0241 (Dawson and Logan, TASI 2008). That paper writes `V = +\mu^2 \phi^\dagger\phi + \lambda (\phi^\dagger\phi)^2` with `\mu^2 < 0`, which is the same potential as `-\mu^2|\phi|^2 + \lambda|\phi|^4` after the sign of `\mu^2` is absorbed, and `M_H = \sqrt{2\lambda}\,\nu` with `\nu \simeq 246` GeV.
