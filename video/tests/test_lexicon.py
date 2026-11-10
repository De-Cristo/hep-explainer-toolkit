from pathlib import Path

from video.lexicon import apply_lexicon, load_lexicon

RULES = load_lexicon()
ROOT = Path(__file__).resolve().parents[2]


def say(text: str) -> str:
    return apply_lexicon(text, RULES)


def test_default_lexicon_file_is_the_one_the_package_ships():
    assert (ROOT / "video" / "lexicon" / "hep.yaml").is_file()


def test_units_and_the_longer_energy_form():
    assert say("125 GeV") == "125 gigaelectronvolts"
    assert say("a TeV scale") == "a teraelectronvolts scale"
    # The longer form wins; TeV inside it is not rewritten a second time.
    assert say("at 13.6 TeV today") == "at 13.6 teraelectronvolts today"
    assert say("13.6 tev") == "13.6 teraelectronvolts"
    assert say("p = 40 GeV/c") == "p = 40 gigaelectronvolts per c"


def test_inverse_femtobarns():
    assert say("10 fb^-1") == "10 inverse femtobarns"
    assert say("10 fb^{-1}") == "10 inverse femtobarns"
    assert say("10 fb⁻¹") == "10 inverse femtobarns"
    assert say("10 fb-1") == "10 inverse femtobarns"


def test_processes_and_symbols():
    assert say("J/psi and J/ψ") == "J psi and J psi"
    assert say("ttbar") == "t t bar"
    assert say(r"t\bar{t}") == "t t bar"
    assert say("H->bb") == "H to b b"
    assert say("H→bb") == "H to b b"
    assert say("ZH and WH") == "Z H and W H"
    assert say("WHAT is not a process") == "WHAT is not a process"
    assert say("p_T and pT") == "p T and p T"
    assert say("chi-squared and χ²") == "kye squared and kye squared"
    assert say("σ, η, φ") == "sigma, eta, phi"
    # The words are already pronounced correctly; do not mangle them.
    assert say("eta and phi") == "eta and phi"


def test_jargon_sentence_from_the_toy_deck():
    spoken = say("J/psi, ttbar, 13.6 TeV, 10 fb^-1, H->bb, ZH, WH, p_T, eta, phi, sigma, and chi-squared.")
    assert "J psi" in spoken
    assert "t t bar" in spoken
    assert "13.6 teraelectronvolts" in spoken
    assert "inverse femtobarns" in spoken
    assert "H to b b" in spoken
    assert "Z H" in spoken and "W H" in spoken
    assert "p T" in spoken
    assert "eta" in spoken and "phi" in spoken and "sigma" in spoken
    assert "kye squared" in spoken
    assert "fb^" not in spoken
    assert "ttbar" not in spoken
    assert "TeV" not in spoken
