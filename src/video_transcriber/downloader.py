"""Download audio from European Parliament webstreaming and video URLs."""

import json
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs as stdlib_parse_qs
from urllib.parse import urlencode, urlparse, urlunparse

import requests
import yt_dlp

EP_WEBSTREAMING_PATTERN = re.compile(
    r"https?://multimedia\.europarl\.europa\.eu/(?P<lang>\w+)/webstreaming/"
    r"(?:[^_]*_)?(?P<id>[\w-]+)"
)

EP_VIDEO_PATTERN = re.compile(
    r"https?://multimedia\.europarl\.europa\.eu/(?P<lang>\w+)/video/"
    r"(?:[^_]*_)?(?P<id>[\w-]+)"
)

GLCLOUD_CONTENT_URL = "https://control.eup.glcloud.eu/content-manager/content-page/{video_id}"

EP_MULTIMEDIA_API_URL = "https://multimedia.europarl.europa.eu"


def extract_meeting_ref(url):
    """Extract a reference ID from an EP webstreaming or video URL.

    Examples:
        .../webstreaming/committees_20260317-1430-COMMITTEE-EMPL → 20260317-1430-COMMITTEE-EMPL
        .../video/some-title_I242316 → I242316

    Returns the extracted reference, or None.
    """
    # Try webstreaming-style meeting reference first
    match = re.search(r"(\d{8}-\d{4}-[\w-]+)$", url.rstrip("/"))
    if match:
        return match.group(1)
    # Try video-style ID (e.g. _I242316)
    match = re.search(r"_([A-Z]\d+)$", url.rstrip("/"))
    if match:
        return match.group(1)
    return None


def _resolve_video_clip_url(url):
    """Try to resolve video clip URL by scraping the EP multimedia page.

    Video clips (e.g. /video/..._I242316) may not be available through the
    glcloud content-page API. This function fetches the multimedia page
    directly and looks for the video source URL in meta tags, embedded
    JSON-LD data, or player configuration.

    Args:
        url: EP multimedia video clip URL.

    Returns:
        A video download URL (MP4 or HLS), or None if not found.
    """
    print("Trying to resolve video from EP multimedia page...", file=sys.stderr)
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"Could not fetch multimedia page: {e}", file=sys.stderr)
        return None

    html = resp.text

    # Strategy 1: Look for og:video meta tag (most reliable for video clips)
    og_match = re.search(
        r'<meta\s+(?:property|name)=["\']og:video(?::url)?["\']\s+'
        r'content=["\'](https?://[^"\']+)["\']',
        html,
    )
    if og_match:
        video_url = og_match.group(1)
        print("Found video URL via og:video meta tag", file=sys.stderr)
        return video_url

    # Also try reversed attribute order (content before property)
    og_match = re.search(
        r'<meta\s+content=["\'](https?://[^"\']+)["\']\s+'
        r'(?:property|name)=["\']og:video(?::url)?["\']',
        html,
    )
    if og_match:
        video_url = og_match.group(1)
        print("Found video URL via og:video meta tag", file=sys.stderr)
        return video_url

    # Strategy 2: Look for JSON-LD with video content URL
    jsonld_matches = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    for jsonld_text in jsonld_matches:
        try:
            ld_data = json.loads(jsonld_text)
            # Handle both single objects and arrays
            items = ld_data if isinstance(ld_data, list) else [ld_data]
            for item in items:
                content_url = item.get("contentUrl") or item.get("embedUrl")
                if content_url:
                    print("Found video URL via JSON-LD", file=sys.stderr)
                    return content_url
        except (json.JSONDecodeError, AttributeError):
            continue

    # Strategy 3: Look for direct .mp4 or .m3u8 URLs in the page
    mp4_match = re.search(
        r'["\'](https?://[^"\']*\.(?:mp4|m3u8)[^"\']*)["\']',
        html,
    )
    if mp4_match:
        video_url = mp4_match.group(1)
        print("Found video URL in page source", file=sys.stderr)
        return video_url

    # Strategy 4: Look for an embedded glcloud iframe with a different URL pattern
    iframe_match = re.search(
        r'<iframe[^>]+src=["\'](https?://[^"\']*glcloud[^"\']*)["\']',
        html,
    )
    if iframe_match:
        iframe_url = iframe_match.group(1)
        print(f"Found glcloud iframe URL: {iframe_url}", file=sys.stderr)
        # Try to fetch the iframe page and extract the stream from there
        try:
            iframe_resp = requests.get(
                iframe_url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=30,
            )
            iframe_resp.raise_for_status()
            ng_match = re.search(
                r'<script[^>]*id="ng-state"[^>]*>(.*?)</script>',
                iframe_resp.text,
                re.DOTALL,
            )
            if ng_match:
                ng_data = json.loads(ng_match.group(1))
                stream_info = ng_data.get("contentEventKey")
                if not stream_info:
                    for _key, value in ng_data.items():
                        if isinstance(value, dict) and "contentEventKey" in value:
                            stream_info = value["contentEventKey"]
                            break
                if stream_info and stream_info.get("playerUrl"):
                    return stream_info["playerUrl"]
        except Exception:
            pass

    print("Could not find video URL in multimedia page.", file=sys.stderr)
    return None


def _resolve_stream_info(url, audio_track=None):
    """Resolve stream info from the EP's new glcloud infrastructure.

    The EP migrated from connectedviews.eu to control.eup.glcloud.eu in
    early 2025. This function fetches the content page and extracts the
    HLS player URL and metadata from the embedded ng-state JSON.

    Args:
        url: EP webstreaming URL.
        audio_track: Audio track language code (e.g. 'or' for original floor,
                     'de' for German interpreter, 'en' for English interpreter).
                     If None, uses the URL's language parameter.

    Returns:
        dict with keys: hls_url, start_time, end_time, final_vod, title,
        or None if not an EP URL.
    """
    match = EP_WEBSTREAMING_PATTERN.match(url) or EP_VIDEO_PATTERN.match(url)
    if not match:
        return None

    lang = match.group("lang") or "en"
    video_id = match.group("id")

    audio = audio_track if audio_track else lang

    params = {
        "lang": lang,
        "audio": audio,
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
            "Could not find stream info in EP metadata. The stream may not be available yet."
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


def download_audio(url, output_dir=None, audio_track=None):
    """Download audio from an EP webstreaming or video URL.

    First tries to resolve the HLS stream URL via the EP's glcloud
    infrastructure, then falls back to yt-dlp's built-in extractor.
    Downloads and converts to 16kHz mono WAV for Whisper.

    Args:
        url: EP webstreaming or video URL.
        output_dir: Directory to save the audio file.
                    If None, uses a temp directory.
        audio_track: Audio track language code (e.g. 'or' for original floor,
                     'de' for German interpreter). None uses the URL's language.

    Returns:
        Path to the downloaded audio file (WAV, 16kHz mono).
    """
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="video_transcriber_")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    meeting_ref = extract_meeting_ref(url) or "audio"
    # Append track suffix to filename to avoid overwriting when downloading
    # multiple tracks for the same meeting.
    if audio_track:
        meeting_ref = f"{meeting_ref}_{audio_track}"
    output_template = str(output_dir / meeting_ref)

    # Try to resolve the HLS URL from the new EP infrastructure
    download_url = url
    extra_ydl_opts = {}
    resolved_hls = False
    try:
        info = _resolve_stream_info(url, audio_track=audio_track)
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
            f"Warning: Could not resolve stream via glcloud API ({e}). ",
            file=sys.stderr,
        )
        # For video clips, try scraping the multimedia page for a direct URL
        if EP_VIDEO_PATTERN.match(url):
            clip_url = _resolve_video_clip_url(url)
            if clip_url:
                download_url = clip_url
                if clip_url.endswith(".m3u8") or ".m3u8" in clip_url:
                    resolved_hls = True
                    extra_ydl_opts["http_headers"] = {
                        "Referer": url,
                        "Origin": "https://multimedia.europarl.europa.eu",
                    }
                else:
                    # Direct MP4 or other format — yt-dlp can handle these
                    extra_ydl_opts["http_headers"] = {
                        "Referer": url,
                    }
            else:
                print("Falling back to yt-dlp extractor.", file=sys.stderr)
        else:
            print("Falling back to yt-dlp extractor.", file=sys.stderr)

    # If we resolved an HLS URL, try downloading directly with ffmpeg first
    # since yt-dlp's generic extractor may not handle raw m3u8 URLs well.
    if resolved_hls:
        wav_path = output_dir / f"{meeting_ref}.wav"
        try:
            import subprocess

            print(
                "Downloading audio with ffmpeg (this may take a while for long meetings)...",
                file=sys.stderr,
            )
            ffmpeg_cmd = [
                "ffmpeg",
                "-y",
                "-headers",
                "Referer: https://control.eup.glcloud.eu/\r\n",
                "-i",
                download_url,
                "-vn",  # no video
                "-ar",
                "16000",  # 16kHz sample rate
                "-ac",
                "1",  # mono
                "-c:a",
                "pcm_s16le",  # WAV format
                "-stats",  # show progress stats
                str(wav_path),
            ]
            # Don't capture output — let ffmpeg progress show in terminal
            result = subprocess.run(
                ffmpeg_cmd,
                stdin=subprocess.DEVNULL,
                timeout=7200,  # 2 hour timeout for long meetings
            )
            if result.returncode == 0 and wav_path.exists():
                return str(wav_path)
            else:
                print(
                    f"ffmpeg failed (exit {result.returncode}), trying yt-dlp...",
                    file=sys.stderr,
                )
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
