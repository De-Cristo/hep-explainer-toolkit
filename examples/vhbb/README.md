# VH(bb) audience benchmark

This project is the v0.2 end-to-end benchmark for audience-aware HEP explanations.

The scientific support is shared, but the explanations are not simple vocabulary rewrites:

- `scenes/public.yaml` starts from the identification problem and explains why an accompanying W or Z adds event information.
- `scenes/student.yaml` connects the VH production topology to reconstructed b-tagged jets and lepton categories.
- `scenes/specialist.yaml` states the public channel definition, 2017 dataset scope, and combined-VH quantitative result.

All three variants reference `claims.yaml`. The public measurement claims are grounded in CMS arXiv:1808.08242. The b-jet object distinction uses CMS arXiv:1712.07158. The explanatory Higgs-strahlung diagrams use the public Higgs review hep-ph/0503172.

The claim registry deliberately keeps `interpretation: pending`. Source declaration, stored evidence, and matched numerical values do not substitute for a human review of whether each audience-specific sentence preserves the intended scientific meaning.

## Validate

From the repository root:

```bash
python -m checks.claims check examples/vhbb/claims.yaml --report build/vhbb-claims.md

python -m checks.explanation examples/vhbb/scenes/public.yaml
python -m checks.explanation examples/vhbb/scenes/student.yaml
python -m checks.explanation examples/vhbb/scenes/specialist.yaml
```

`checks.explanation` uses the same explicit render-job construction as `video.explain`. It checks language, provenance, number traceability, citations, diagram physics, storyboard structure, and the sealed dependency set without generating audio or video.

## Render

With the video dependencies installed:

```bash
python -m video.explain examples/vhbb/scenes/public.yaml -o build/vhbb-public.mp4
python -m video.explain examples/vhbb/scenes/student.yaml -o build/vhbb-student.mp4
python -m video.explain examples/vhbb/scenes/specialist.yaml -o build/vhbb-specialist.mp4
```

The student and public variants use semantic diagram cues. The specialist variant keeps the process picture stable while quantitative scope is stated.

## What this benchmark tests

A successful build demonstrates that:

1. audience briefs can demand different prerequisite chains and learning goals;
2. several explanations can reuse stable scientific claim IDs;
3. narration segments can cite different claims precisely;
4. spoken numbers are traced through the project source manifest;
5. semantic narration cues select diagram states;
6. the exact files checked are sealed before rendering.

This benchmark is intentionally small. It is a reproducible architecture test, not a replacement for a full experimental analysis note or a complete public outreach production.
