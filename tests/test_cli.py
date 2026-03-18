"""Tests for the CLI module."""

from video_transcriber.cli import format_segments, format_timestamp, parse_args

SAMPLE_SEGMENTS = [
    {"start": 0.0, "end": 3.5, "text": " Hello everyone."},
    {"start": 3.5, "end": 8.2, "text": " Welcome to today's committee meeting."},
    {"start": 10.0, "end": 15.7, "text": " Let us begin with the first item on the agenda."},
]

SAMPLE_SEGMENTS_WITH_LANG = [
    {"start": 0.0, "end": 3.5, "text": " Hello everyone.", "language": "en"},
    {"start": 3.5, "end": 8.2, "text": " Willkommen.", "language": "de"},
]


def test_parse_args_minimal():
    args = parse_args(["https://example.com/video"])
    assert args.url == "https://example.com/video"
    assert args.model == "base"
    assert args.language is None
    assert args.task == "transcribe"
    assert args.format == "txt"
    assert args.output is None
    assert args.mode == "simple"
    assert args.clean is False
    assert args.audio_track is None


def test_parse_args_full():
    args = parse_args(
        [
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
        ]
    )
    assert args.output == "out.srt"
    assert args.model == "large-v3"
    assert args.language == "fr"
    assert args.task == "translate"
    assert args.format == "srt"
    assert args.keep_audio is True
    assert args.audio_dir == "/tmp/audio"


def test_parse_args_new_options():
    args = parse_args(
        [
            "https://example.com/video",
            "--mode",
            "auto",
            "--clean",
            "--audio-track",
            "de",
        ]
    )
    assert args.mode == "auto"
    assert args.clean is True
    assert args.audio_track == "de"


def test_parse_args_transcript():
    args = parse_args(["https://example.com/video", "--transcript"])
    assert args.transcript is True


def test_parse_args_transcript_default():
    args = parse_args(["https://example.com/video"])
    assert args.transcript is False


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


def test_format_segments_txt_with_language():
    output = format_segments(SAMPLE_SEGMENTS_WITH_LANG, "txt")
    lines = output.split("\n")
    assert "[EN]" in lines[0]
    assert "[DE]" in lines[1]


def test_format_segments_srt():
    output = format_segments(SAMPLE_SEGMENTS, "srt")
    assert "1\n00:00:00,000 --> 00:00:03,500\nHello everyone." in output
    assert "2\n00:00:03,500 --> 00:00:08," in output


def test_format_segments_vtt():
    output = format_segments(SAMPLE_SEGMENTS, "vtt")
    assert output.startswith("WEBVTT\n")
    assert "00:00:00.000 --> 00:00:03.500" in output


SAMPLE_SEGMENTS_WITH_SPEAKERS = [
    {"start": 0.0, "end": 3.5, "text": " Hello from Alice.", "speaker": "Alice SMITH"},
    {"start": 3.5, "end": 8.2, "text": " More from Alice.", "speaker": "Alice SMITH"},
    {"start": 10.0, "end": 15.7, "text": " Hello from Bob.", "speaker": "Bob JONES"},
]


def test_format_segments_txt_with_speakers():
    output = format_segments(SAMPLE_SEGMENTS_WITH_SPEAKERS, "txt")
    lines = output.split("\n")
    # Speaker shown on first occurrence only
    assert "[Alice SMITH]" in lines[0]
    assert "[Alice SMITH]" not in lines[1]  # Same speaker, no repeat
    assert "[Bob JONES]" in lines[2]


def test_format_segments_srt_with_speakers():
    output = format_segments(SAMPLE_SEGMENTS_WITH_SPEAKERS, "srt")
    assert "[Alice SMITH] Hello from Alice." in output
    assert "[Alice SMITH] More from Alice." in output
    assert "[Bob JONES] Hello from Bob." in output


def test_format_segments_md_with_speakers():
    output = format_segments(SAMPLE_SEGMENTS_WITH_SPEAKERS, "md")
    assert "**Alice SMITH:**" in output
    assert "**Bob JONES:**" in output
