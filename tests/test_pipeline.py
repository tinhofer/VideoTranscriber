"""Tests for the pipeline module."""

from video_transcriber.pipeline import _collect_interpreter_segments, _find_closest_segment

INTERP_SEGMENTS = [
    {"start": 0.0, "end": 5.0, "text": "Guten Tag."},
    {"start": 5.0, "end": 10.0, "text": "Willkommen zur Sitzung."},
    {"start": 15.0, "end": 20.0, "text": "Der Bericht ist fertig."},
]


def test_find_closest_segment_exact():
    seg = _find_closest_segment(0.0, 5.0, INTERP_SEGMENTS)
    assert seg is not None
    assert seg["text"] == "Guten Tag."


def test_find_closest_segment_overlap():
    seg = _find_closest_segment(3.0, 7.0, INTERP_SEGMENTS)
    assert seg is not None
    # Should match the segment with most overlap


def test_find_closest_segment_no_match():
    seg = _find_closest_segment(50.0, 55.0, INTERP_SEGMENTS)
    assert seg is None


def test_collect_interpreter_segments_full_range():
    result = _collect_interpreter_segments(INTERP_SEGMENTS, 0.0, 25.0)
    assert len(result) == 3


def test_collect_interpreter_segments_partial():
    result = _collect_interpreter_segments(INTERP_SEGMENTS, 3.0, 7.0)
    assert len(result) == 2
    assert result[0]["text"] == "Guten Tag."
    assert result[1]["text"] == "Willkommen zur Sitzung."


def test_collect_interpreter_segments_none():
    result = _collect_interpreter_segments(INTERP_SEGMENTS, 25.0, 30.0)
    assert len(result) == 0
