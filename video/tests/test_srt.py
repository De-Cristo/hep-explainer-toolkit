from video.srt import format_timestamp, render_srt, wrap_cue


def test_timestamp_and_wrap():
    assert format_timestamp(0) == "00:00:00,000"
    assert format_timestamp(3.2) == "00:00:03,200"
    assert format_timestamp(3661.25) == "01:01:01,250"
    wrapped = wrap_cue("one two three four five", width=10)
    assert wrapped.splitlines() == ["one two", "three four", "five"]


def test_render_is_standard_srt():
    text = render_srt([(0.0, 1.5, "Hello there"), (1.5, 3.0, "Second cue")])
    assert text.startswith("1\n00:00:00,000 --> 00:00:01,500\nHello there\n")
    assert "\n\n2\n00:00:01,500 --> 00:00:03,000\nSecond cue\n" in text
