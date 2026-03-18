"""Tests for the downloader module."""

from video_transcriber.downloader import extract_meeting_ref


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
