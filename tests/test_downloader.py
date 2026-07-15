"""Tests for the downloader module."""

from video_transcriber.downloader import (
    _build_audio_stream_map,
    _extract_transcript_url,
    _find_srt_urls,
    _parse_srt_timestamp,
    extract_meeting_ref,
    is_ep_url,
    merge_speakers_into_segments,
    normalize_ep_url,
    parse_chapter_speaker,
    parse_srt,
)

# --- URL normalization tests ---


def test_normalize_streaming_event_url():
    url = "https://www.europarl.europa.eu/streaming/?event=20260709-1400-SPECIAL-OTHER"
    assert normalize_ep_url(url) == (
        "https://multimedia.europarl.europa.eu/en/webstreaming/20260709-1400-SPECIAL-OTHER"
    )


def test_normalize_streaming_event_url_no_www():
    url = "https://europarl.europa.eu/streaming/?event=20260709-1400-SPECIAL-OTHER"
    assert normalize_ep_url(url) == (
        "https://multimedia.europarl.europa.eu/en/webstreaming/20260709-1400-SPECIAL-OTHER"
    )


def test_normalize_streaming_url_with_extra_params():
    url = (
        "https://www.europarl.europa.eu/streaming/"
        "?event=20260709-1400-SPECIAL-OTHER&language=de"
    )
    assert normalize_ep_url(url) == (
        "https://multimedia.europarl.europa.eu/en/webstreaming/20260709-1400-SPECIAL-OTHER"
    )


def test_normalize_leaves_canonical_ep_url_unchanged():
    url = (
        "https://multimedia.europarl.europa.eu/en/webstreaming/"
        "committees_20260317-1430-COMMITTEE-EMPL"
    )
    assert normalize_ep_url(url) == url


def test_normalize_leaves_non_ep_url_unchanged():
    url = "https://www.youtube.com/watch?v=abc123"
    assert normalize_ep_url(url) == url


def test_is_ep_url_accepts_streaming_event_url():
    url = "https://www.europarl.europa.eu/streaming/?event=20260709-1400-SPECIAL-OTHER"
    assert is_ep_url(url)


def test_extract_meeting_ref_from_streaming_url():
    url = "https://www.europarl.europa.eu/streaming/?event=20260709-1400-SPECIAL-OTHER"
    assert extract_meeting_ref(normalize_ep_url(url)) == "20260709-1400-SPECIAL-OTHER"


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


# --- HTML entity decoding tests ---


def test_parse_srt_html_entities():
    srt = (
        "1\n00:00:01,000 --> 00:00:05,000\n"
        "SOUNDBITE (Original), Ib&aacute;n GARC&#205;A DEL BLANCO (S&amp;D, ES), -\n"
    )
    segments = parse_srt(srt)
    assert len(segments) == 1
    assert "Ibán" in segments[0]["text"]
    assert "GARCÍA" in segments[0]["text"]
    assert "S&D" in segments[0]["text"]
    assert "&amp;" not in segments[0]["text"]


def test_parse_srt_numeric_html_entities():
    srt = "1\n00:00:01,000 --> 00:00:02,000\nKosma Z&#321;OTOWSKI (ECR, PL)\n"
    segments = parse_srt(srt)
    assert "ZŁOTOWSKI" in segments[0]["text"]


# --- Speaker parsing tests ---


def test_parse_chapter_speaker_basic():
    text = "SOUNDBITE (Original), Deirdre CLUNE (EPP, IE), -"
    assert parse_chapter_speaker(text) == "Deirdre CLUNE"


def test_parse_chapter_speaker_with_group():
    text = "SOUNDBITE (Original), Sergey LAGODINSKY (Greens/EFA, DE), -"
    assert parse_chapter_speaker(text) == "Sergey LAGODINSKY"


def test_parse_chapter_speaker_end_marker():
    assert parse_chapter_speaker("End") is None


def test_parse_chapter_speaker_no_match():
    assert parse_chapter_speaker("Some random text") is None


def test_parse_chapter_speaker_decoded_entities():
    text = "SOUNDBITE (Original), Ibán GARCÍA DEL BLANCO (S&D, ES), -"
    assert parse_chapter_speaker(text) == "Ibán GARCÍA DEL BLANCO"


# --- Speaker merging tests ---


def test_merge_speakers_basic():
    chapters = [
        {"start": 0.0, "end": 120.0, "text": "SOUNDBITE (Original), Alice SMITH (EPP, DE), -"},
        {"start": 120.0, "end": 240.0, "text": "SOUNDBITE (Original), Bob JONES (S&D, FR), -"},
        {"start": 240.0, "end": 300.0, "text": "End"},
    ]
    whisper = [
        {"start": 5.0, "end": 10.0, "text": "Hello from Alice."},
        {"start": 60.0, "end": 65.0, "text": "More from Alice."},
        {"start": 130.0, "end": 135.0, "text": "Hello from Bob."},
    ]
    result = merge_speakers_into_segments(whisper, chapters)
    assert result[0]["speaker"] == "Alice SMITH"
    assert result[1]["speaker"] == "Alice SMITH"
    assert result[2]["speaker"] == "Bob JONES"


def test_merge_speakers_no_chapters():
    whisper = [{"start": 0.0, "end": 5.0, "text": "Hello."}]
    result = merge_speakers_into_segments(whisper, [])
    assert "speaker" not in result[0]


def test_merge_speakers_no_match():
    chapters = [
        {"start": 100.0, "end": 200.0, "text": "SOUNDBITE (Original), Alice SMITH (EPP, DE), -"},
    ]
    whisper = [{"start": 0.0, "end": 5.0, "text": "Before any speaker."}]
    result = merge_speakers_into_segments(whisper, chapters)
    assert "speaker" not in result[0]


# --- Audio stream map tests ---


def test_build_audio_stream_map_none():
    assert _build_audio_stream_map(None) == []


def test_build_audio_stream_map_original():
    result = _build_audio_stream_map("or")
    assert result == ["-map", "0:m:language:qaa"]


def test_build_audio_stream_map_german():
    result = _build_audio_stream_map("de")
    assert result == ["-map", "0:m:language:ger"]


def test_build_audio_stream_map_english():
    result = _build_audio_stream_map("en")
    assert result == ["-map", "0:m:language:eng"]


def test_build_audio_stream_map_french():
    result = _build_audio_stream_map("fr")
    assert result == ["-map", "0:m:language:fre"]


def test_build_audio_stream_map_unknown_passthrough():
    result = _build_audio_stream_map("ger")
    assert result == ["-map", "0:m:language:ger"]
