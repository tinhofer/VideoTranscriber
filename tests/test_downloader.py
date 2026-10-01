"""Tests for the downloader module."""

import shutil
import subprocess

import pytest

from video_transcriber.downloader import (
    _build_audio_stream_map,
    _build_hls_url,
    _check_audio_silence,
    _extract_transcript_url,
    _find_srt_urls,
    _parse_hls_audio_renditions,
    _parse_m3u8_attributes,
    _parse_mean_volume,
    _parse_srt_timestamp,
    _refine_hls_audio_url,
    _resolve_stream_info,
    _select_audio_rendition,
    extract_meeting_ref,
    is_ep_url,
    merge_speakers_into_segments,
    normalize_ep_url,
    parse_chapter_speaker,
    parse_glcloud_url,
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
    url = "https://www.europarl.europa.eu/streaming/?event=20260709-1400-SPECIAL-OTHER&language=de"
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


# --- Glcloud clip URL tests ---


GLCLOUD_CLIP_URL = (
    "https://control.eup.glcloud.eu/content-manager/content-page/"
    "20260714-1515-COMMITTEE-IMCO"
    "?audio=en&start=1784035974&end=1784039247&lang=en&logo=true&multicast=true"
)


def test_parse_glcloud_url_full():
    clip = parse_glcloud_url(GLCLOUD_CLIP_URL)
    assert clip["event_id"] == "20260714-1515-COMMITTEE-IMCO"
    assert clip["start"] == 1784035974
    assert clip["end"] == 1784039247
    assert clip["audio"] == "en"
    assert clip["lang"] == "en"


def test_parse_glcloud_url_without_times():
    url = (
        "https://control.eup.glcloud.eu/content-manager/content-page/"
        "20260714-1515-COMMITTEE-IMCO?audio=de"
    )
    clip = parse_glcloud_url(url)
    assert clip["event_id"] == "20260714-1515-COMMITTEE-IMCO"
    assert clip["start"] is None
    assert clip["end"] is None
    assert clip["audio"] == "de"
    assert clip["lang"] == "en"  # default


def test_parse_glcloud_url_non_matching():
    assert parse_glcloud_url("https://www.youtube.com/watch?v=abc123") is None
    assert (
        parse_glcloud_url(
            "https://multimedia.europarl.europa.eu/en/webstreaming/"
            "committees_20260317-1430-COMMITTEE-EMPL"
        )
        is None
    )


def test_is_ep_url_accepts_glcloud_clip_url():
    assert is_ep_url(GLCLOUD_CLIP_URL)


def test_extract_meeting_ref_glcloud_url_ignores_query():
    assert extract_meeting_ref(GLCLOUD_CLIP_URL) == "20260714-1515-COMMITTEE-IMCO"


def test_build_hls_url_clip_appends_times_even_for_final_vod():
    info = {
        "hls_url": "https://cdn.example.eu/index.m3u8",
        "final_vod": True,
        "clip": True,
        "start_time": 1784035974,
        "end_time": 1784039247,
    }
    url = _build_hls_url(info)
    assert "startTime=1784035974" in url
    assert "endTime=1784039247" in url


def test_build_hls_url_final_vod_without_clip_unchanged():
    info = {
        "hls_url": "https://cdn.example.eu/index.m3u8",
        "final_vod": True,
        "start_time": 1,
        "end_time": 2,
    }
    assert _build_hls_url(info) == "https://cdn.example.eu/index.m3u8"


class _FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def _fake_ng_page(start_time, end_time, final_vod):
    import json

    state = {
        "contentEventKey": {
            "playerUrl": "https://cdn.example.eu/index.m3u8",
            "startTime": start_time,
            "endTime": end_time,
            "finalVod": final_vod,
            "live": False,
            "title": "IMCO Committee",
        }
    }
    return f'<html><script id="ng-state">{json.dumps(state)}</script></html>'


def test_resolve_stream_info_glcloud_clip(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return _FakeResponse(_fake_ng_page(1784030000, 1784050000, True))

    monkeypatch.setattr("video_transcriber.downloader.requests.get", fake_get)
    info = _resolve_stream_info(GLCLOUD_CLIP_URL)
    # Clip bounds from the URL override the event metadata
    assert info["start_time"] == 1784035974
    assert info["end_time"] == 1784039247
    assert info["clip"] is True
    # audio= from the URL is used as the default track
    assert captured["params"]["audio"] == "en"
    # Clip range is forwarded to the content-page request
    assert captured["params"]["start"] == "1784035974"
    assert captured["params"]["end"] == "1784039247"
    assert captured["url"].endswith("20260714-1515-COMMITTEE-IMCO")
    # Final HLS URL contains the clip range despite finalVod=True
    hls = _build_hls_url(info)
    assert "startTime=1784035974" in hls
    assert "endTime=1784039247" in hls


def test_resolve_stream_info_glcloud_audio_track_overrides_url(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["params"] = params
        return _FakeResponse(_fake_ng_page(1, 2, False))

    monkeypatch.setattr("video_transcriber.downloader.requests.get", fake_get)
    _resolve_stream_info(GLCLOUD_CLIP_URL, audio_track="de")
    # Explicit --audio-track wins over audio= from the URL
    assert captured["params"]["audio"] == "de"


def test_resolve_stream_info_webstreaming_unchanged(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["params"] = params
        return _FakeResponse(_fake_ng_page(100, 200, False))

    monkeypatch.setattr("video_transcriber.downloader.requests.get", fake_get)
    url = (
        "https://multimedia.europarl.europa.eu/en/webstreaming/"
        "committees_20260317-1430-COMMITTEE-EMPL"
    )
    info = _resolve_stream_info(url)
    assert info["start_time"] == 100
    assert info["end_time"] == 200
    assert "clip" not in info
    assert "start" not in captured["params"]
    assert captured["params"]["audio"] == "en"


def test_resolve_stream_info_sends_browser_headers(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["headers"] = headers
        return _FakeResponse(_fake_ng_page(100, 200, False))

    monkeypatch.setattr("video_transcriber.downloader.requests.get", fake_get)
    _resolve_stream_info(
        "https://multimedia.europarl.europa.eu/en/webstreaming/"
        "committees_20261001-0900-COMMITTEE-EMPL"
    )
    headers = captured["headers"]
    # The glcloud content page (Akamai) answers 403 unless the request looks
    # like a browser page load: full UA, Accept-Language and Sec-Fetch-*.
    assert "Chrome/" in headers["User-Agent"]
    assert headers["Accept-Language"]
    for name in ("Sec-Fetch-Dest", "Sec-Fetch-Mode", "Sec-Fetch-Site", "Sec-Fetch-User"):
        assert headers[name]


# --- HLS manifest / audio rendition tests ---


SAMPLE_MASTER_MANIFEST = """\
#EXTM3U
#EXT-X-VERSION:6
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Original",LANGUAGE="or",DEFAULT=YES,\
URI="audio/or/index.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="German",LANGUAGE="de",DEFAULT=NO,\
URI="audio/de/index.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="French",LANGUAGE="fr",DEFAULT=NO,\
URI="audio/fr/index.m3u8"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",LANGUAGE="en",URI="subs/en.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=2000000,AUDIO="audio"
video/index.m3u8
"""


def test_parse_m3u8_attributes():
    attrs = _parse_m3u8_attributes('TYPE=AUDIO,NAME="Original (floor)",DEFAULT=YES,URI="a.m3u8"')
    assert attrs["TYPE"] == "AUDIO"
    assert attrs["NAME"] == "Original (floor)"
    assert attrs["DEFAULT"] == "YES"
    assert attrs["URI"] == "a.m3u8"


def test_parse_hls_audio_renditions():
    renditions = _parse_hls_audio_renditions(SAMPLE_MASTER_MANIFEST)
    # Subtitle entry must be excluded
    assert len(renditions) == 3
    assert renditions[0]["name"] == "Original"
    assert renditions[0]["language"] == "or"
    assert renditions[0]["default"] is True
    assert renditions[1]["uri"] == "audio/de/index.m3u8"


def test_parse_hls_audio_renditions_media_playlist():
    """A media playlist (no EXT-X-MEDIA) yields no renditions."""
    media_playlist = "#EXTM3U\n#EXT-X-TARGETDURATION:6\nsegment0.ts\n"
    assert _parse_hls_audio_renditions(media_playlist) == []


def test_select_audio_rendition_floor_by_language():
    renditions = _parse_hls_audio_renditions(SAMPLE_MASTER_MANIFEST)
    assert _select_audio_rendition(renditions, "or")["name"] == "Original"


def test_select_audio_rendition_floor_by_name():
    renditions = [
        {"name": "Original (floor)", "language": "", "uri": "a.m3u8", "default": True},
        {"name": "German", "language": "", "uri": "b.m3u8", "default": False},
    ]
    assert _select_audio_rendition(renditions, "or")["uri"] == "a.m3u8"


def test_select_audio_rendition_floor_by_qaa():
    renditions = [{"name": "", "language": "qaa", "uri": "a.m3u8", "default": True}]
    assert _select_audio_rendition(renditions, "or")["uri"] == "a.m3u8"


def test_select_audio_rendition_language_variants():
    for lang in ("de", "deu", "ger", "de-DE"):
        renditions = [
            {"name": "", "language": "fr", "uri": "fr.m3u8", "default": False},
            {"name": "", "language": lang, "uri": "de.m3u8", "default": False},
        ]
        selected = _select_audio_rendition(renditions, "de")
        assert selected["uri"] == "de.m3u8", f"failed for LANGUAGE={lang}"


def test_select_audio_rendition_by_full_language_name():
    renditions = [
        {"name": "French", "language": "", "uri": "fr.m3u8", "default": False},
        {"name": "German", "language": "", "uri": "de.m3u8", "default": False},
    ]
    assert _select_audio_rendition(renditions, "de")["uri"] == "de.m3u8"


def test_select_audio_rendition_en_does_not_match_french():
    """'en' must not substring-match NAME="French"."""
    renditions = [{"name": "French", "language": "", "uri": "fr.m3u8", "default": False}]
    assert _select_audio_rendition(renditions, "en") is None


def test_select_audio_rendition_no_match():
    renditions = _parse_hls_audio_renditions(SAMPLE_MASTER_MANIFEST)
    assert _select_audio_rendition(renditions, "mt") is None
    assert _select_audio_rendition(renditions, None) is None


# Live-archive manifests (observed on 20261001-0900-COMMITTEE-EMPL) name the
# renditions audio01..audio32 with private-use LANGUAGE codes. The track
# order comes from the content page's languageMapping instead.
SAMPLE_NUMBERED_MANIFEST = """\
#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="AUDIO",NAME="audio30",LANGUAGE="qaj",DEFAULT=YES,\
URI="input/1/32/norsk-archive.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="AUDIO",NAME="audio01",LANGUAGE="qbf",DEFAULT=NO,\
URI="input/1/257/norsk-archive.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="AUDIO",NAME="audio02",LANGUAGE="qbd",DEFAULT=NO,\
URI="input/1/258/norsk-archive.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="AUDIO",NAME="audio04",LANGUAGE="qbc",DEFAULT=NO,\
URI="input/1/260/norsk-archive.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="AUDIO",NAME="audio29",LANGUAGE="qaa",DEFAULT=NO,\
URI="input/1/285/norsk-archive.m3u8"
"""

SAMPLE_LANGUAGE_MAPPING = [
    {"lang": "OR", "sort": 1},
    {"lang": "EN", "sort": 8},
    {"lang": "FR", "sort": 9},
    {"lang": "DE", "sort": 6},
    None,
]


def test_select_audio_rendition_by_language_mapping():
    renditions = _parse_hls_audio_renditions(SAMPLE_NUMBERED_MANIFEST)
    for track, name in (("en", "audio02"), ("de", "audio04"), ("EN", "audio02")):
        selected = _select_audio_rendition(renditions, track, SAMPLE_LANGUAGE_MAPPING)
        assert selected["name"] == name, f"failed for track={track}"


def test_select_audio_rendition_mapping_beats_qaa_alias():
    """'or' must follow the mapping (audio01), not LANGUAGE="qaa" (audio29)."""
    renditions = _parse_hls_audio_renditions(SAMPLE_NUMBERED_MANIFEST)
    selected = _select_audio_rendition(renditions, "or", SAMPLE_LANGUAGE_MAPPING)
    assert selected["name"] == "audio01"


def test_select_audio_rendition_mapping_without_rendition():
    """Mapped language whose audioNN rendition is missing yields no match."""
    renditions = _parse_hls_audio_renditions(SAMPLE_NUMBERED_MANIFEST)
    assert _select_audio_rendition(renditions, "fr", SAMPLE_LANGUAGE_MAPPING) is None


def test_select_audio_rendition_mapping_ignored_for_named_manifest():
    """A mapping must not disturb manifests with real NAME/LANGUAGE metadata."""
    renditions = _parse_hls_audio_renditions(SAMPLE_MASTER_MANIFEST)
    selected = _select_audio_rendition(renditions, "de", SAMPLE_LANGUAGE_MAPPING)
    assert selected["name"] == "German"


def test_refine_hls_audio_url_uses_language_mapping(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _FakeManifestResponse(SAMPLE_NUMBERED_MANIFEST)

    monkeypatch.setattr("video_transcriber.downloader.requests.get", fake_get)
    master = "https://cdn.example.eu/event/master-archive.m3u8?startTime=100&endTime=200"
    refined = _refine_hls_audio_url(master, "en", SAMPLE_LANGUAGE_MAPPING)
    assert refined.startswith("https://cdn.example.eu/event/input/1/258/norsk-archive.m3u8")
    assert "startTime=100" in refined


def test_resolve_stream_info_returns_language_mapping(monkeypatch):
    import json

    state = {
        "contentEventKey": {
            "playerUrl": "https://cdn.example.eu/master-archive.m3u8",
            "languageMapping": SAMPLE_LANGUAGE_MAPPING,
        }
    }
    page = f'<html><script id="ng-state">{json.dumps(state)}</script></html>'

    def fake_get(url, params=None, headers=None, timeout=None):
        return _FakeResponse(page)

    monkeypatch.setattr("video_transcriber.downloader.requests.get", fake_get)
    info = _resolve_stream_info(
        "https://multimedia.europarl.europa.eu/en/webstreaming/"
        "committees_20261001-0900-COMMITTEE-EMPL"
    )
    assert info["language_mapping"] == SAMPLE_LANGUAGE_MAPPING


class _FakeManifestResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def test_refine_hls_audio_url_picks_rendition(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _FakeManifestResponse(SAMPLE_MASTER_MANIFEST)

    monkeypatch.setattr("video_transcriber.downloader.requests.get", fake_get)
    master = "https://cdn.example.eu/event/index.m3u8?startTime=100&endTime=200"
    refined = _refine_hls_audio_url(master, "or")
    # Relative URI resolved against the master URL
    assert refined.startswith("https://cdn.example.eu/event/audio/or/index.m3u8")
    # Time range carried over from the master URL
    assert "startTime=100" in refined
    assert "endTime=200" in refined


def test_refine_hls_audio_url_media_playlist_unchanged(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _FakeManifestResponse("#EXTM3U\n#EXT-X-TARGETDURATION:6\nseg0.ts\n")

    monkeypatch.setattr("video_transcriber.downloader.requests.get", fake_get)
    master = "https://cdn.example.eu/event/channel-04-bxl/index.m3u8"
    assert _refine_hls_audio_url(master, "or") == master


def test_refine_hls_audio_url_no_match_unchanged(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _FakeManifestResponse(SAMPLE_MASTER_MANIFEST)

    monkeypatch.setattr("video_transcriber.downloader.requests.get", fake_get)
    master = "https://cdn.example.eu/event/index.m3u8"
    assert _refine_hls_audio_url(master, "mt") == master


def test_refine_hls_audio_url_fetch_error_unchanged(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr("video_transcriber.downloader.requests.get", fake_get)
    master = "https://cdn.example.eu/event/index.m3u8"
    assert _refine_hls_audio_url(master, "or") == master


def test_refine_hls_audio_url_no_track_skips_fetch(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        raise AssertionError("should not fetch when no track requested")

    monkeypatch.setattr("video_transcriber.downloader.requests.get", fake_get)
    master = "https://cdn.example.eu/event/index.m3u8"
    assert _refine_hls_audio_url(master, None) == master


# --- Silence check tests ---


def test_parse_mean_volume():
    output = (
        "[Parsed_volumedetect_0 @ 0x55] n_samples: 160000\n"
        "[Parsed_volumedetect_0 @ 0x55] mean_volume: -23.4 dB\n"
        "[Parsed_volumedetect_0 @ 0x55] max_volume: -5.0 dB\n"
    )
    assert _parse_mean_volume(output) == -23.4
    assert _parse_mean_volume("mean_volume: -91.0 dB") == -91.0
    assert _parse_mean_volume("no volume info here") is None


_FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None


@pytest.mark.skipif(not _FFMPEG_AVAILABLE, reason="ffmpeg not on PATH")
def test_check_audio_silence_raises_for_silent_wav(tmp_path):
    silent_wav = tmp_path / "silent.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono",
            "-t",
            "2",
            "-c:a",
            "pcm_s16le",
            str(silent_wav),
        ],
        check=True,
        capture_output=True,
    )
    with pytest.raises(RuntimeError, match="silent"):
        _check_audio_silence(silent_wav)


@pytest.mark.skipif(not _FFMPEG_AVAILABLE, reason="ffmpeg not on PATH")
def test_check_audio_silence_passes_for_audible_wav(tmp_path):
    tone_wav = tmp_path / "tone.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000",
            "-t",
            "2",
            "-c:a",
            "pcm_s16le",
            str(tone_wav),
        ],
        check=True,
        capture_output=True,
    )
    # Must not raise
    _check_audio_silence(tone_wav)


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
