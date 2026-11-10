# checks

CMS rules as checks, not as text in a prompt. A public export from `video/` is not ready until the confidentiality gate passes. The traceability check is the claim check: every number on a slide or in the narration has a declared source.

These checks do not relax the repository rule. Internal or unapproved CMS material is never committed here. The fixtures under `checks/tests/fixtures/` are invented toy values, labelled TOY, and are not measurements.

## Dependencies

Python 3.12 and the standard library only. There is no third-party package. Run every command from the repository root so `import checks` resolves.

```bash
python3 -m unittest discover -s checks/tests -t . -v
python3 -m checks.confidentiality scan PATH
python3 -m checks.traceability check PATH --manifest sources.yaml
```

YAML configs use a small subset: indentation with spaces, mappings, lists, quoted strings, booleans, and numbers. Anchors, tags, and `|` / `>` block scalars are rejected.

## 1. Confidentiality gate

An internal plot often has no marker word, so the gate is an allowlist. Every image, plot-data file (JSON, CSV, or a `*datacard*` text file), slide HTML file, and narration source must appear in the same `sources.yaml` the number check uses, with a public source:

| `source.type` | What it requires |
|---|---|
| `hepdata` | a record URL or id |
| `arxiv` | an id `NNNN.NNNNN` |
| `cds` | an `https://cds.cern.ch/...` link, or a `CMS-PAS-...` id |
| `toy` | a generator script under `examples/toy/` and a `sha256` |

`source: toy` with nothing else is refused. The check reruns `python3 <generator> OUTPUT` and the sha256 of that output must equal both the file on disk and the manifest. The generator has to live under `examples/toy/` so a copied plot cannot be waved through by a script elsewhere.

```yaml
files:
  - path: talk.html
    source:
      type: arxiv
      arxiv: "0000.00000"
  - path: toy_plot.png
    source:
      type: toy
      generator: examples/toy/emit.py
      sha256: "<64 hex chars>"
```

A file with no row is a failure (`undeclared`), including an unlabelled PNG that contains none of the marker phrases. Paths are relative to the manifest and must stay inside the deck.

The marker scan below is an extra layer on top of that allowlist. It still fails the run when a declared public file carries an internal marker. The marker list is [`config/markers.yaml`](config/markers.yaml).

| Rule id | Result | What it matches |
|---|---|---|
| `cms_private_work` | fail | `CMS Private Work`, `CMS Private`, `Private Work` / `Private work` |
| `cms_internal` | fail | `CMS Internal`, `CMS Internal Note`, `internal note` |
| `work_in_progress` | fail unless explicitly allowed | `Work in progress`, `Work-in-progress` |
| `preliminary` | warning only | `Preliminary`, `CMS Preliminary` |
| `analysis_note` | fail | `AN-2099-000`, `CMS-AN-2099/000`, `AN-2024-000` |
| `detector_note` | fail | `DN-2099-001` and the same shapes |
| `cadi_line` | fail unless a public id for that same code is present | `HIG-00-000` and the other groups listed in the config (`GROUP-YY-NNN` or `GROUP-YYYY-NNN`) |
| `twiki_viewauth` | fail | `twiki.cern.ch/.../viewauth/` |
| `twiki_cms_web` | fail | `twiki.cern.ch/.../view/CMS/...` but not `CMSPublic` |
| `cms_cern_ch` | fail | `https://cms.cern.ch/...` |
| `cms_docdb` | fail | `cms-docdb.cern.ch` |
| `indico_private` | fail | an Indico URL that contains `/manage`, `/edit`, `/review`, `protection`, or `access=private` |

`CMS Simulation` is not a failure. A normal `https://indico.cern.ch/event/<id>/` URL is not a failure either.

A CADI-style code is cleared, and reported as an exemption, when the same file contains a public id built from that code (`CMS-PAS-HIG-00-000`, `CMS-HIG-00-000`, `PAS HIG-00-000`) or when an allow file names the code and a reference. An arXiv id sitting next to the code does not clear it. An analysis-note number is never cleared that way.

### What is scanned

- HTML (frontend-slides-PKU), including text split by inline tags such as `<em>`, plus Markdown, narration, SVG, TeX, and other text extensions in the config
- PDF text operators, including FlateDecode streams
- image filenames (underscores and hyphens are treated as spaces) and cheap metadata: PNG `tEXt` / `zTXt` / `iTXt`, JPEG `COM`, GIF comments
- `data:image/...;base64,...` images embedded in a slide, via the same metadata readers

Pixels are not read. There is no OCR.

### Allowing "Work in progress"

The rule fails closed. To allow it for one project, either pass the rule id or drop a file named `confidentiality-allow.yaml` in the scanned directory:

```yaml
allow_markers:
  - work_in_progress
public_cadi:
  - code: HIG-00-000
    reference: "arXiv:0000.00000 (toy, not a real paper)"
```

```bash
python3 -m checks.confidentiality scan slides/my-talk
python3 -m checks.confidentiality scan slides/my-talk --allow-marker work_in_progress
python3 -m checks.confidentiality scan slides/my-talk --json
python3 -m checks.confidentiality scan slides/my-talk --strict   # warnings fail too
```

The allow file itself is not scanned. Exit codes are `0` (no failures; warnings are allowed), `1` (a failure, or a warning in `--strict`), and `2` (config or allow file cannot be read).

Policy documents that name the markers are listed as `exempt_paths` in the config (`INVENTORY.md`, `plots/README.md`, this file). Hits there are counted as quiet exemptions. `checks/tests/` and `checks/config/` are not scanned, because the fixtures and the marker list contain the phrases on purpose.

### Pre-commit and pull requests

[`.pre-commit-config.yaml`](../.pre-commit-config.yaml) runs the gate on every commit:

```bash
pip install pre-commit   # developer tool, not a dependency of the check
pre-commit install
```

The hook uses `python3` and scans the tree from the repository root. [`.github/workflows/checks.yml`](../.github/workflows/checks.yml) runs the unit tests and the same gate on pull requests, on Python 3.12.

## 2. Number traceability

Every number in the slide text and every number in the narration (the text that would be sent to TTS) must match one manifest row, not merely equal some value that appears somewhere in the source. A row can name `quantity` (`mu`, `cross_section`), `process` (`WH`, `ZH`, ...), `kind` (`central`, `stat`, `syst`, `total`), and `unit`. The checker reads those same words next to the number: the nearest process token, a `(stat)` / `(syst)` / `(total)` label, and the unit. `1.31 ± 0.26 (stat) ± 0.24 (syst)` does not match a source whose statistical uncertainty is 0.24 and whose systematic uncertainty is 0.26, even though both numbers exist. `WH mu = 1.07` does not match the ZH value 1.07.

A separate wording lint rejects a signal strength (`mu`, `μ`, or "signal strength") that is called a cross section or given a cross-section unit (`pb`, `fb`, `nb`, ...). Wording mistakes outside that rule are not caught. Exemptions come only from the allow list, and each one is printed with the rule id.

The public CMS VH(bb) values used in the tests are WH mu = 1.31 ± 0.24 (stat) ± 0.26 (syst) and ZH mu = 1.07 ± 0.17 (stat) ± 0.17 (syst).

```bash
python3 -m checks.traceability check slides/my-talk --manifest slides/my-talk/sources.yaml
python3 -m checks.traceability check slides/my-talk --verbose
python3 -m checks.traceability check slides/my-talk --json
```

If `--manifest` is omitted, the tool looks for `sources.yaml` or `sources.yml` in the deck directory. Exit `0` when every number matches and every local source file agrees. Exit `1` when a number is unmatched or a local file disagrees with the manifest. Exit `2` when the manifest itself is unusable.

### Where numbers are read

Slides are `*.html`, `*.htm`, `*.md`, `*.markdown`, and `*.pdf`. Narration is a file whose name contains `narration`, `voiceover`, `spoken`, `tts`, `transcript`, or `script` (not `javascript`), or an HTML `data-narration="..."` attribute, or `<script type="application/x-narration">`. Style sheets, ordinary `<script>` tags, and HTML comments are not claims. `README.md` is not a slide.

Spoken forms that are recognised include `one point two`, `thirteen point six teraelectronvolts`, `one hundred thirty-eight inverse femtobarns`, `twelve point five percent`, `plus or minus`, `1.2 ± 0.05`, `1.2 +0.3 -0.1`, `1.2e-3`, `1.2 × 10^{-3}`, and `one point two times ten to the minus three`. A lone small word such as `two` in `two jets` is not taken as a claim. `one hundred ...` and `one point two` are.

Units that convert inside a family: eV / keV / MeV / GeV / TeV; fb⁻¹ / pb⁻¹ / nb⁻¹ / ab⁻¹ (also `fb-1` and `fb^{-1}`); fb / pb / nb as cross sections; `%` and `percent`. A manifest value of `13600` GeV matches a slide that says `13.6 TeV`.

### Manifest

Paths are relative to the manifest file. This example is toy data, not a result.

```yaml
match:
  rounding: half_up          # or none
  absolute_tolerance: 0
  relative_tolerance: 0

# Optional. Discovered automatically when omitted.
inputs:
  slides:
    - talk.html
  narration:
    - narration.txt

sources:
  - id: wh_mu
    quantity: mu
    process: WH
    kind: central
    value: 1.31
    source:
      type: paper
      arxiv: "1808.08242"
  - id: wh_mu_stat
    quantity: mu
    process: WH
    kind: stat
    value: 0.24
    source:
      type: paper
      arxiv: "1808.08242"
  - id: toy_mass
    value: 1.2
    uncertainty: 0.05
    unit: GeV
    source:
      type: fit_json
      path: toy_fit.json
      key: mass
      uncertainty_key: mass_unc
  - id: toy_lumi
    value: 138
    unit: "fb-1"
    source:
      type: hepdata
      record: "https://www.hepdata.net/record/toy0001"
  - id: toy_rate
    value: 0.42
    unit: pb
    source:
      type: datacard
      path: toy_datacard.txt
      key: rate
      index: 0
  - id: toy_energy
    value: 13.6
    unit: TeV
    source:
      type: paper
      arxiv: "0000.00000"
      cds: CERN-EP-TOY-0001
```

`source.type` is `hepdata`, `fit_json`, `datacard`, or `paper`.

- `fit_json` and `datacard` must point at a local file. The value at `key` (dotted path for JSON, a datacard line such as `rate 0.42`) has to agree with the manifest under the same rounding rule. A wrong file is a failure even when the slides match the manifest.
- `hepdata` needs a record URL, an id, or a string that contains `hepdata`. `paper` needs `arxiv` (`NNNN.NNNNN`), `cds`, `doi` (starts with `10.`), or an `http` URL. Those records are not downloaded.

### Rounding

With `rounding: half_up` and both tolerances at `0`, a shown number matches when the source, converted into the shown unit, rounds half-up (away from zero on a tie) to the last digit the author wrote.

- `1.2` matches `1.2` and matches `1.24` (rounds to `1.2`). It does not match `1.3`.
- `1.25` shown as `1.3` matches. Shown as `1.2` does not.
- `1.2e-3` and `1.2 × 10^{-3}` carry quantum `0.0001`.
- A non-zero `absolute_tolerance` or `relative_tolerance` also accepts a value within `max(absolute, relative * |source|)`, even when the rounding disagrees. The default is zero, so only the rounding rule applies.
- If the slide shows `±`, the manifest uncertainty has to round the same way. A central value with no uncertainty still matches a source that has one.

Set `allow_defaults: false` to ignore the shipped allow list and supply `allow:` yourself.

The default allow list is [`config/traceability_allow.yaml`](config/traceability_allow.yaml):

| Rule id | What it exempts |
|---|---|
| `slide_numbers` | `#pageNumber`, a footer `N / M`, and the words `slide N` / `page N` |
| `years` | a unitless integer from 1990 through 2100 |
| `urls` | digits inside `http://` or `https://` |
| `arxiv` | an `arXiv:NNNN.NNNNN` id |
| `timestamps` | `HH:MM:SS` timestamps |
| `dotted_versions` | `1.2.3` software versions |
| `fenced_code` | Markdown fences and HTML `<pre>` |

Add a `literal` rule in the manifest for other non-physics numbers (`kind: literal`, `values: [1920, 1080]`).

## Blind spots

Confidentiality:

- No OCR. A marker drawn only as pixels in a plot is invisible. Metadata and the filename are what get read.
- PDF text in a custom encoding, an encrypted PDF, or a page that is only an image yields no text. Files larger than `max_file_bytes` (80 MB) are truncated and warned.
- `https://indico.cern.ch/event/<id>/` is not flagged. A restricted event can use that same shape.
- The bare word `internal` is not a marker. `CMS Internal` and `internal note` are.
- A CADI code is cleared by a same-file public id or by a string in the allow file. The check does not open the citation or prove it describes that analysis.
- `checks/tests/`, `checks/config/`, `upstream/`, and the allow file are not scanned. A deck placed on an `exempt_paths` entry is reported as an exemption instead of a failure.
- `Preliminary` warns and does not fail the gate unless `--strict` is set.
- The allowlist covers images, plot data, slide HTML, and narration. Other files are only marker-scanned. A base64 image inside HTML is not a separate row; it is covered by the HTML file's declaration, and the marker layer still reads its metadata.

Traceability:

- Histogram bins, Plotly arrays inside `<script>`, and numbers painted inside a figure are not claims. Only visible text and the narration string are.
- HEPData, CDS, and arXiv are not re-fetched. A well-formed id is trusted. Local JSON and datacards are opened.
- A comma is a thousands separator (`138,000`), not a decimal comma.
- Half-up rounding accepts a coarser quote when that quote is the correctly rounded source (`13.6` shown as `14`).
- A four-digit year in 1990–2100 is exempt even if a count happens to land on a year. URL digits, arXiv ids, versions, timestamps, and fenced code are exempt by the default allow file.
- A shown number with no unit can match a source that has a unit when the raw values agree, except a `mu` or `signal_strength` row, which rejects any unit.
- An unused manifest row is not an error. A number with no nearby process word is not tied to a process, so `1.07` alone can still match whichever row has that value.
- Wording is checked only by a small quantity rule: a signal strength (`mu`, `μ`, or "signal strength") must not be called a cross section and must not be given a cross-section unit (`pb`, `fb`, ...). Other wording mistakes are not caught. That includes the wrong production channel when the process token is missing, "observed" versus "expected", and synonyms outside the process list `WH`, `ZH`, `ttH`, `tH`, `ggH`, `VBF`, `VH`, `bbH`.
