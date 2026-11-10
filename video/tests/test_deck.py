from pathlib import Path

from video.deck import parse_slides, resolve_deck_inputs, walk_states

TOY = Path(__file__).resolve().parents[1] / "examples" / "toy-peak"


def test_toy_deck_has_three_slides_and_six_states():
    html = (TOY / "deck.html").read_text(encoding="utf-8")
    slides = parse_slides(html)
    assert [(s.number, s.max_step) for s in slides] == [(1, 0), (2, 2), (3, 1)]
    assert walk_states(slides) == [
        (1, 0),
        (2, 0),
        (2, 1),
        (2, 2),
        (3, 0),
        (3, 1),
    ]


def test_folder_resolution_finds_the_toy_pair():
    html, narration = resolve_deck_inputs(TOY, None)
    assert html.name == "deck.html"
    assert narration.name == "narration.yaml"


def test_a_scaffold_title_slide_is_step_zero_only():
    html = """
    <section class="slide title-slide visible" data-header="hidden">
      <h1>Title</h1>
    </section>
    <section class="slide normal-slide">
      <li class="st" data-st="1">one</li>
      <li class="st" data-st="1">also one</li>
      <li class="st" data-st="3">three</li>
    </section>
    """
    slides = parse_slides(html)
    assert [s.max_step for s in slides] == [0, 3]
    assert walk_states(slides) == [(1, 0), (2, 0), (2, 1), (2, 2), (2, 3)]
