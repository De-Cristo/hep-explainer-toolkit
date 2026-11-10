# diagrams

One diagram description, two pictures.

```bash
python3 -m diagrams figure examples/theory/vh/wh.yaml -o out/wh.png --svg out/wh.svg
python3 -m diagrams animate examples/theory/vh/wh.yaml -o build/wh.mp4
python3 -m diagrams equation 'M_H=\sqrt{2\lambda}\,\nu' -o out/mass.png
```

`figure` runs TikZ-Feynman through `pdflatex` (vertices are placed by hand, so Lua layout is not required) and `pdftocairo`. The preamble loads `physics` and `siunitx`. `animate` draws the same resolved spec in Manim 0.22.1.

Do not set `arrow` unless you mean to override the helper. With no arrow, the line follows fermion number: with the momentum for a particle, against it for an antiparticle. `source` → `target` is the momentum. The check in `python3 -m checks.diagrams check` compares that spec with the Standard Model UFO and with the excerpt's vertex list.

Allowed vertices come from `checks/models/sm-ufo`, not from a list kept next to the drawing code. See `checks/models/PROVENANCE.md`.
