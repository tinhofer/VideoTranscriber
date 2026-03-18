"""Tests for the downloader module."""

from video_transcriber.downloader import (
    _extract_transcript_url,
    _find_srt_urls,
    _parse_srt_timestamp,
    extract_meeting_ref,
    parse_srt,
)


def test_extract_meeting_ref_committee():
    url = (
        "https://multimedia.europarl.europa.eu/en/webstreaming/"
        "committees_20260317-1430-COMMITTEE-EMPL"
    )
    assert extract_meeting_ref(url) == "20260317-1430-COMMITTEE-EMPL"


def test_extract_meeting_ref_plenary():
    url = (
        "https://multimedia.europarl.europa.eu/en/webstreaming/"
        "plenary-session_20260317-0900-PLENARY"
    )
    assert extract_meeting_ref(url) == "20260317-0900-PLENARY"


def test_extract_meeting_ref_trailing_slash():
    url = (
        "https://multimedia.europarl.europa.eu/en/webstreaming/"
        "committees_20260317-1430-COMMITTEE-EMPL/"
    )
    assert extract_meeting_ref(url) == "20260317-1430-COMMITTEE-EMPL"


def test_extract_meeting_ref_video_clip():
    url = (
        "https://multimedia.europarl.europa.eu/en/video/"
        "artificial-intelligence-act-closing-statements_I242316"
    )
    assert extract_meeting_ref(url) == "I242316"


def test_extract_meeting_ref_video_clip_trailing_slash():
    url = "https://multimedia.europarl.europa.eu/en/video/some-video-title_I999999/"
    assert extract_meeting_ref(url) == "I999999"


def test_extract_meeting_ref_no_match():
    assert extract_meeting_ref("https://example.com/random") is None


# --- SRT parsing tests ---


SAMPLE_SRT = """\
1
00:00:01,000 --> 00:00:04,500
Hello everyone.

2
00:00:05,200 --> 00:00:09,800
Welcome to today's committee meeting.

3
00:00:10,000 --> 00:00:15,700
Let us begin with the first item
on the agenda.
"""


def test_parse_srt_basic():
    segments = parse_srt(SAMPLE_SRT)
    assert len(segments) == 3
    assert segments[0]["start"] == 1.0
    assert segments[0]["end"] == 4.5
    assert segments[0]["text"] == "Hello everyone."
    assert segments[1]["start"] == 5.2
    assert segments[1]["end"] == 9.8
    assert segments[1]["text"] == "Welcome to today's committee meeting."


def test_parse_srt_multiline_text():
    segments = parse_srt(SAMPLE_SRT)
    # Third segment has multiline text — should be joined
    assert segments[2]["text"] == "Let us begin with the first item on the agenda."


def test_parse_srt_empty():
    assert parse_srt("") == []
    assert parse_srt("   \n\n  ") == []


def test_parse_srt_no_sequence_numbers():
    """SRT without sequence numbers should still parse (just timestamps + text)."""
    srt = "00:00:01,000 --> 00:00:02,000\nHello.\n\n00:00:03,000 --> 00:00:04,000\nWorld.\n"
    segments = parse_srt(srt)
    assert len(segments) == 2
    assert segments[0]["text"] == "Hello."
    assert segments[1]["text"] == "World."


def test_parse_srt_dot_separator():
    """Accept dot as decimal separator (common in some SRT variants)."""
    srt = "1\n00:00:01.500 --> 00:00:03.200\nTest segment.\n"
    segments = parse_srt(srt)
    assert len(segments) == 1
    assert segments[0]["start"] == 1.5
    assert segments[0]["end"] == 3.2


def test_parse_srt_timestamp():
    assert _parse_srt_timestamp("00:00:00,000") == 0.0
    assert _parse_srt_timestamp("00:01:01,500") == 61.5
    assert _parse_srt_timestamp("01:01:01,123") == 3661.123
    assert _parse_srt_timestamp("00:00:05.200") == 5.2
    assert _parse_srt_timestamp("invalid") is None


# --- Transcript URL extraction tests ---


def test_find_srt_urls():
    data = {
        "a": "https://example.com/file.srt",
        "b": {"nested": "/docs/transcript.srt?download=true"},
        "c": [1, "not-a-url", "https://example.com/video.mp4"],
    }
    urls = _find_srt_urls(data)
    assert len(urls) == 2
    assert "https://example.com/file.srt" in urls
    assert "/docs/transcript.srt?download=true" in urls


def test_find_srt_urls_empty():
    assert _find_srt_urls({}) == []
    assert _find_srt_urls({"a": "no srt here"}) == []


def test_extract_transcript_url_from_related_items():
    page_props = {
        "relatedItems": [
            {
                "type": "Shotlist",
                "url": "https://api.ep.eu/docs/shotlist.pdf",
                "format": "pdf",
            },
            {
                "type": "Transcript",
                "url": "https://api.ep.eu/docs/I242315[SD-EN].srt?download=true",
                "format": "srt",
            },
        ],
    }
    url = _extract_transcript_url(page_props)
    assert url == "https://api.ep.eu/docs/I242315[SD-EN].srt?download=true"


def test_extract_transcript_url_language_filter():
    page_props = {
        "relatedItems": [
            {
                "type": "Transcript",
                "url": "https://api.ep.eu/docs/I242315[SD-EN].srt?download=true",
                "format": "srt",
            },
            {
                "type": "Transcript",
                "url": "https://api.ep.eu/docs/I242315[SD-DE].srt?download=true",
                "format": "srt",
            },
        ],
    }
    url = _extract_transcript_url(page_props, language="de")
    assert "[SD-DE]" in url


def test_extract_transcript_url_fallback_to_srt_search():
    """When no structured relatedItems, fall back to recursive URL search."""
    page_props = {
        "mediaItemV2": {
            "someField": {
                "deep": "https://api.ep.eu/docs/transcript.srt?download=true",
            }
        }
    }
    url = _extract_transcript_url(page_props)
    assert url == "https://api.ep.eu/docs/transcript.srt?download=true"


def test_extract_transcript_url_none_when_missing():
    page_props = {"mediaItemV2": {"mediaAssets": [{"type": "video", "url": "http://x.mp4"}]}}
    assert _extract_transcript_url(page_props) is None
