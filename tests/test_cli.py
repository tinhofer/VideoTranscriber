"""Tests for the CLI module."""

from video_transcriber.cli import format_segments, format_timestamp, parse_args


SAMPLE_SEGMENTS = [
    {"start": 0.0, "end": 3.5, "text": " Hello everyone."},
    {"start": 3.5, "end": 8.2, "text": " Welcome to today's committee meeting."},
    {"start": 10.0, "end": 15.7, "text": " Let us begin with the first item on the agenda."},
]


def test_parse_args_minimal():
    args = parse_args(["https://example.com/video"])
    assert args.url == "https://example.com/video"
    assert args.model == "base"
    assert args.language is None
    assert args.task == "transcribe"
    assert args.format == "txt"
    assert args.output is None


def test_parse_args_full():
    args = parse_args([
        "https://example.com/video",
        "-o",
        "out.srt",
        "--model",
        "large-v3",
        "--language",
        "fr",
        "--task",
        "translate",
        "--format",
        "srt",
        "--keep-audio",
        "--audio-dir",
        "/tmp/audio",
    ])
    assert args.output == "out.srt"
    assert args.model == "large-v3"
    assert args.language == "fr"
    assert args.task == "translate"
    assert args.format == "srt"
    assert args.keep_audio is True
    assert args.audio_dir == "/tmp/audio"


def test_format_timestamp():
    assert format_timestamp(0) == "00:00:00,000"
    assert format_timestamp(61.5) == "00:01:01,500"
    assert format_timestamp(3661.123) == "01:01:01,123"


def test_format_segments_txt():
    output = format_segments(SAMPLE_SEGMENTS, "txt")
    lines = output.split("\n")
    assert len(lines) == 3
    assert lines[0] == "[00:00:00] Hello everyone."
    assert lines[1] == "[00:00:03] Welcome to today's committee meeting."


def test_format_segments_srt():
    output = format_segments(SAMPLE_SEGMENTS, "srt")
    assert "1\n00:00:00,000 --> 00:00:03,500\nHello everyone." in output
    assert "2\n00:00:03,500 --> 00:00:08," in output


def test_format_segments_vtt():
    output = format_segments(SAMPLE_SEGMENTS, "vtt")
    assert output.startswith("WEBVTT\n")
    assert "00:00:00.000 --> 00:00:03.500" in output
