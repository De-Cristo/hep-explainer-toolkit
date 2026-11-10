# Agent instructions

This repository is public. Use public sources only: arXiv, a DOI, or a textbook those papers cite. Do not add CMS-internal material, and do not call a paid LLM API. The person already has an agent. This file says which command to run.

Plots and slides are optional. A theory explanation does not need a CMS plot.

## 1. Pick the output

Read the request and pick the smallest thing that answers it.

| The request needs | `visual.kind` | Command |
|---|---|---|
| One static picture of a formula or a layout | `slide` or `figure` | `python3 -m diagrams equation '...' -o out.png`, or point `visual.file` at an existing image |
| A Feynman diagram as a figure | `diagram` with `motion: still` | `python3 -m diagrams figure DIAGRAM.yaml -o out.png --svg out.svg` |
| The same diagram moving | `manim` or `diagram` with `motion: build` | `python3 -m diagrams animate DIAGRAM.yaml -o build/clip.mp4` |
| A deck of existing slides, narrated | the deck pipeline, not a scene file | `python3 render-video.py DECK/` |
| A short narrated film made of any mix of the above | a scene file | `python3 -m video.explain SCENE.yaml -o build/name.mp4` |

Use a plot (`visual.kind: plot`, or `plots/`) only when the request is about a measured or toy distribution. Do not invent one for a theory explanation.

`video.explain` holds each still for the length of its narration and, if a Manim clip is shorter than the narration, freezes the last frame until the audio ends. Do not ship a clip whose picture and sound differ by more than 0.2 s.

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

## 5. Before you finish

From the repository root:

```bash
python3 -m checks.diagrams check PATH/scene.yaml
python3 -m checks.confidentiality scan .
python3 -m unittest discover -s checks/tests -t . -v
pytest video/tests -q -m "not smoke"
```

`checks.diagrams check` prints a side-by-side of each item and the excerpt it cites. Read it. Exit 0 is not a substitute for that reading when the claim is prose: the quote is stored and shown, and a person decides whether the sentence follows.

Images, SVG, and narration files need a `sources.yaml` next to them (`files:` with `source.type` of `arxiv`, `hepdata`, `cds`, or a toy generator). The provenance rule accepts a new-style arXiv id (`NNNN.NNNNN`) only. An old id such as `hep-ph/0503172` is fine inside a scene citation and is not accepted as the `files:` source type. Commit PNG and SVG. Leave MP4, WAV, and Manim `media/` out of git. Write videos under `build/`.

If the scene speaks a number, the traceability check still applies. `python3 -m checks.traceability check PATH --manifest sources.yaml`.

## 6. Examples

- `examples/theory/vh/` — `q qbar' → W* → WH`, `H → b bbar`, and `q qbar → Z* → ZH`. Stills are in `out/`. The narrated film is built, not committed.
- `examples/theory/higgs/` — the potential, the vacuum value, and `M_H = \sqrt{2\lambda}\,\nu`, quoted from arXiv:0901.0241 (Dawson and Logan, TASI 2008). That paper writes `V = +\mu^2 \phi^\dagger\phi + \lambda (\phi^\dagger\phi)^2` with `\mu^2 < 0`, which is the same potential as `-\mu^2|\phi|^2 + \lambda|\phi|^4` after the sign of `\mu^2` is absorbed, and `M_H = \sqrt{2\lambda}\,\nu` with `\nu \simeq 246` GeV.
