"""Download audio from European Parliament webstreaming URLs."""

import json
import re
import sys
import tempfile
from pathlib import Path

import requests
import yt_dlp


EP_URL_PATTERN = re.compile(
    r"https?://multimedia\.europarl\.europa\.eu/(?P<lang>\w+)/webstreaming/"
    r"(?:[^_]*_)?(?P<id>[\w-]+)"
)

GLCLOUD_CONTENT_URL = (
    "https://control.eup.glcloud.eu/content-manager/content-page/{video_id}"
)


def extract_meeting_ref(url):
    """Extract the meeting reference from an EP webstreaming URL.

    Example URL:
        https://multimedia.europarl.europa.eu/en/webstreaming/
            committees_20260317-1430-COMMITTEE-EMPL

    Returns the part after the last underscore or slash that looks like
    a meeting reference (e.g. '20260317-1430-COMMITTEE-EMPL').
    """
    match = re.search(r"(\d{8}-\d{4}-[\w-]+)$", url.rstrip("/"))
    if match:
        return match.group(1)
    return None


def _resolve_hls_url(url):
    """Resolve the HLS stream URL from the EP's new glcloud infrastructure.

    The EP migrated from connectedviews.eu to control.eup.glcloud.eu in
    early 2025. This function fetches the content page and extracts the
    HLS player URL from the embedded ng-state JSON.

    Returns:
        HLS (m3u8) URL string, or None if not found.
    """
    match = EP_URL_PATTERN.match(url)
    if not match:
        return None

    lang = match.group("lang") or "en"
    video_id = match.group("id")

    params = {
        "lang": lang,
        "audio": lang,
        "autoplay": "true",
        "logo": "false",
        "muted": "false",
        "fullscreen": "true",
        "disclaimer": "false",
        "multicast": "true",
        "analytics": "false",
    }

    print(f"Resolving stream from EP glcloud API...", file=sys.stderr)

    resp = requests.get(
        GLCLOUD_CONTENT_URL.format(video_id=video_id),
        params=params,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    resp.raise_for_status()

    # Extract ng-state JSON from the content page
    ng_match = re.search(
        r'<script[^>]*id="ng-state"[^>]*>(.*?)</script>',
        resp.text,
        re.DOTALL,
    )
    if not ng_match:
        raise RuntimeError(
            "Could not find stream metadata in EP content page. "
            "The EP streaming infrastructure may have changed again."
        )

    ng_data = json.loads(ng_match.group(1))

    # Navigate to contentEventKey which contains stream info
    stream_info = ng_data.get("contentEventKey")
    if not stream_info:
        # Try to find it nested somewhere
        for key, value in ng_data.items():
            if isinstance(value, dict) and "contentEventKey" in value:
                stream_info = value["contentEventKey"]
                break

    if not stream_info:
        raise RuntimeError(
            "Could not find stream info in EP metadata. "
            "The stream may not be available yet."
        )

    player_url = stream_info.get("playerUrl")
    if not player_url:
        raise RuntimeError(
            "No player URL found. The stream may not have started yet "
            "or may no longer be available."
        )

    return player_url


def download_audio(url, output_dir=None):
    """Download audio from an EP webstreaming URL.

    First tries to resolve the HLS stream URL via the EP's new glcloud
    infrastructure, then falls back to yt-dlp's built-in extractor.
    Downloads and converts to 16kHz mono WAV for Whisper.

    Args:
        url: EP webstreaming URL.
        output_dir: Directory to save the audio file.
                    If None, uses a temp directory.

    Returns:
        Path to the downloaded audio file (WAV, 16kHz mono).
    """
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="video_transcriber_")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    meeting_ref = extract_meeting_ref(url) or "audio"
    output_template = str(output_dir / meeting_ref)

    # Try to resolve the HLS URL from the new EP infrastructure
    download_url = url
    try:
        hls_url = _resolve_hls_url(url)
        if hls_url:
            print(f"Resolved HLS stream URL", file=sys.stderr)
            download_url = hls_url
    except Exception as e:
        print(
            f"Warning: Could not resolve stream via glcloud API ({e}). "
            f"Falling back to yt-dlp extractor.",
            file=sys.stderr,
        )

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
            },
        ],
        "postprocessor_args": [
            "-ar",
            "16000",
            "-ac",
            "1",
        ],
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([download_url])

    wav_path = output_dir / f"{meeting_ref}.wav"
    if wav_path.exists():
        return str(wav_path)

    # yt-dlp may append different extensions; find the output file
    for f in output_dir.iterdir():
        if f.stem == meeting_ref:
            return str(f)

    raise FileNotFoundError(
        f"Downloaded audio not found in {output_dir}. "
        "Check that ffmpeg is installed and on your PATH."
    )
