# SM UFO reference

Allowed diagram vertices are read from this directory. They are not a table maintained in the checker.

| | |
|---|---|
| What | FeynRules Standard Model UFO shipped as MadGraph5_aMC@NLO `models/sm` |
| Upstream | <https://github.com/mg5amcnlo/mg5amcnlo> |
| Path | `models/sm/` (`particles.py`, `vertices.py`, and the modules those files import) |
| Commit | `a5b17913ef0b6e1c872016f94d0fb610207dab47` (branch `3.x`, 2026-10-09, "merge with latest 3.5.17") |
| Generator note | `particles.py` header: FeynRules 1.7.69 |
| Licence | `sm-ufo/LICENSE` (MadGraph5_aMC@NLO, NCSA-style). The file headers also name N. Christensen and C. Duhr as the UFO authors. |
| Pin | `sm-ufo/SHA256SUMS` (sha256sum format). `checks.ufo_model` refuses to load if a listed file's digest differs. |

The model is the Feynman-gauge SM with the CKM matrix, Goldstone bosons, and ghosts. Tree-level vertices include `W` couplings of an up-type quark to a down-type quark of any generation, flavour-diagonal `Z` and photon couplings, no photon–neutrino vertex, and `HWW`, `HZZ`, and `Hff` Yukawa vertices for the massive fermions in this export (`c`, `b`, `t`, and the charged leptons). `u`, `d`, and `s` are massless here, so this export has no Yukawa vertex for them.
