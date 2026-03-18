"""Tests for the postprocess module."""

from video_transcriber.postprocess import clean_segments, remove_fillers, remove_repetitions


def test_remove_fillers_german():
    assert "das ist wichtig" in remove_fillers("ähm das ist wichtig")
    assert "ähm" not in remove_fillers("ähm das ist äh wichtig")
    assert "äh" not in remove_fillers("ähm das ist äh wichtig")


def test_remove_fillers_english():
    assert "that is important" in remove_fillers("um that is uh important")
    assert "um" not in remove_fillers("um that is important")
    assert "uh" not in remove_fillers("that is uh important")


def test_remove_fillers_preserves_words():
    # "um" as a real German word (around) should be preserved in context
    # but as a standalone English filler it gets removed. This is a known
    # trade-off — the regex matches whole-word "um".
    result = remove_fillers("We need to discuss this important matter")
    assert result == "We need to discuss this important matter"


def test_remove_repetitions_simple():
    assert remove_repetitions("we must we must act") == "we must act"


def test_remove_repetitions_longer_phrase():
    result = remove_repetitions("I think that I think that we should")
    assert result == "I think that we should"


def test_remove_repetitions_no_change():
    text = "The committee discussed the proposal."
    assert remove_repetitions(text) == text


def test_clean_segments_removes_fillers_and_repetitions():
    segments = [
        {"start": 0.0, "end": 3.0, "text": "ähm we must we must act now"},
        {"start": 3.0, "end": 5.0, "text": "  um  uh  "},  # becomes empty
        {"start": 5.0, "end": 8.0, "text": "This is important."},
    ]
    cleaned = clean_segments(segments)
    # The empty segment should be removed
    assert len(cleaned) == 2
    assert "ähm" not in cleaned[0]["text"]
    assert "we must act now" in cleaned[0]["text"]
    assert cleaned[1]["text"] == "This is important."


def test_clean_segments_preserves_metadata():
    segments = [
        {"start": 1.0, "end": 2.0, "text": "Hello.", "language": "en", "source": "original"},
    ]
    cleaned = clean_segments(segments)
    assert cleaned[0]["language"] == "en"
    assert cleaned[0]["source"] == "original"
    assert cleaned[0]["start"] == 1.0
