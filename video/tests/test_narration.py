import pytest

from video.deck import load_deck, walk_states
from video.narration import check_against_deck, load_script

TOY = __import__("pathlib").Path(__file__).resolve().parents[1] / "examples" / "toy-peak"


def test_toy_script_matches_the_deck_walk():
    script = load_script(TOY / "narration.yaml")
    states = walk_states(load_deck(TOY / "deck.html"))
    assert [(c.slide, c.step) for c in script.steps] == states
    check_against_deck(script, states)
    assert script.voice == "af_sarah"
    assert script.pad_seconds == 0.35
    assert len(script.steps) == 6


def test_duplicate_and_empty_text_are_rejected(tmp_path):
    bad = tmp_path / "narration.yaml"
    bad.write_text(
        "steps:\n"
        "  - {slide: 1, step: 0, text: hello}\n"
        "  - {slide: 1, step: 0, text: again}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_script(bad)

    empty = tmp_path / "empty.yaml"
    empty.write_text("steps:\n  - {slide: 1, step: 0, text: '   '}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        load_script(empty)


def test_order_mismatch_explains_itself():
    script = load_script(TOY / "narration.yaml")
    states = walk_states(load_deck(TOY / "deck.html"))
    swapped = list(reversed(states))
    with pytest.raises(SystemExit, match="presentation order"):
        check_against_deck(script, swapped)
