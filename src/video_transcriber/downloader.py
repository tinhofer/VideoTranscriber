"""Download audio from European Parliament webstreaming URLs."""

import json
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs as stdlib_parse_qs

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


def _resolve_stream_info(url):
    """Resolve stream info from the EP's new glcloud infrastructure.

    The EP migrated from connectedviews.eu to control.eup.glcloud.eu in
    early 2025. This function fetches the content page and extracts the
    HLS player URL and metadata from the embedded ng-state JSON.

    Returns:
        dict with keys: hls_url, start_time, end_time, final_vod, title,
        or None if not an EP URL.
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

    print("Resolving stream from EP glcloud API...", file=sys.stderr)

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

    return {
        "hls_url": player_url,
        "start_time": stream_info.get("startTime"),
        "end_time": stream_info.get("endTime"),
        "final_vod": stream_info.get("finalVod", False),
        "live": stream_info.get("live", False),
        "title": stream_info.get("title"),
    }


def _build_hls_url(info):
    """Build the final HLS URL, adding time range params if needed.

    For non-finalVod streams, the server requires startTime/endTime query
    parameters on the m3u8 URL to return the correct time range.
    """
    hls_url = info["hls_url"]

    # If it's a final VOD, the URL works as-is
    if info.get("final_vod"):
        return hls_url

    # For non-final recordings, append time range if available
    start_time = info.get("start_time")
    end_time = info.get("end_time")
    if start_time and end_time:
        parsed = urlparse(hls_url)
        existing_qs = stdlib_parse_qs(parsed.query)
        existing_qs["startTime"] = [str(start_time)]
        existing_qs["endTime"] = [str(end_time)]
        new_query = urlencode(existing_qs, doseq=True)
        hls_url = urlunparse(parsed._replace(query=new_query))

    return hls_url


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
    extra_ydl_opts = {}
    resolved_hls = False
    try:
        info = _resolve_stream_info(url)
        if info:
            hls_url = _build_hls_url(info)
            print(f"Resolved HLS stream URL: {hls_url[:120]}...", file=sys.stderr)
            download_url = hls_url
            resolved_hls = True
            # The glcloud CDN requires a proper Referer header
            extra_ydl_opts["http_headers"] = {
                "Referer": "https://control.eup.glcloud.eu/",
                "Origin": "https://control.eup.glcloud.eu",
            }
    except Exception as e:
        print(
            f"Warning: Could not resolve stream via glcloud API ({e}). "
            f"Falling back to yt-dlp extractor.",
            file=sys.stderr,
        )

    # If we resolved an HLS URL, try downloading directly with ffmpeg first
    # since yt-dlp's generic extractor may not handle raw m3u8 URLs well.
    if resolved_hls:
        wav_path = output_dir / f"{meeting_ref}.wav"
        try:
            import subprocess
            print("Downloading audio with ffmpeg...", file=sys.stderr)
            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-headers", "Referer: https://control.eup.glcloud.eu/\r\n",
                "-i", download_url,
                "-vn",          # no video
                "-ar", "16000", # 16kHz sample rate
                "-ac", "1",     # mono
                "-c:a", "pcm_s16le",  # WAV format
                str(wav_path),
            ]
            result = subprocess.run(
                ffmpeg_cmd,
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour timeout for long meetings
            )
            if result.returncode == 0 and wav_path.exists():
                return str(wav_path)
            else:
                print(
                    f"ffmpeg failed (exit {result.returncode}), "
                    f"trying yt-dlp...",
                    file=sys.stderr,
                )
                if result.stderr:
                    # Show last few lines of ffmpeg error
                    err_lines = result.stderr.strip().splitlines()[-5:]
                    for line in err_lines:
                        print(f"  ffmpeg: {line}", file=sys.stderr)
        except FileNotFoundError:
            print(
                "ffmpeg not found on PATH, trying yt-dlp...",
                file=sys.stderr,
            )
        except Exception as e:
            print(f"ffmpeg error ({e}), trying yt-dlp...", file=sys.stderr)

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
        **extra_ydl_opts,
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
