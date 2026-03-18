"""Download audio from European Parliament webstreaming and video URLs."""

import html as html_mod
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


def _fetch_next_data(url):
    """Fetch and parse __NEXT_DATA__ from an EP multimedia page.

    Returns:
        The parsed pageProps dict, or None if not found.
    """
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
        return None, None

    html = resp.text
    next_data_match = re.search(
        r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not next_data_match:
        return None, html

    try:
        next_data = json.loads(next_data_match.group(1))
        page_props = next_data.get("props", {}).get("pageProps", {})
        return page_props, html
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"Could not parse __NEXT_DATA__: {e}", file=sys.stderr)
        return None, html


def _resolve_video_clip_url(url):
    """Resolve video clip URL from the EP multimedia page.

    Video clips (e.g. /video/..._I242316) are hosted on Watchity CDN, not
    on the glcloud infrastructure used for webstreaming. The EP multimedia
    page is a Next.js app that embeds all video metadata (including direct
    MP4 download URLs) in a ``<script id="__NEXT_DATA__">`` JSON blob.

    Args:
        url: EP multimedia video clip URL.

    Returns:
        A direct MP4 download URL, or None if not found.
    """
    print("Trying to resolve video from EP multimedia page...", file=sys.stderr)
    page_props, html = _fetch_next_data(url)

    if page_props:
        # Try mediaItemV2.mediaAssets first (has multiple quality levels)
        media_v2 = page_props.get("mediaItemV2", {})
        assets = media_v2.get("mediaAssets", [])
        # Find the best video asset — prefer ORIGINAL, then FHD, HD, SD
        best_url = None
        priority = {"ORIGINAL": 0, "FHD": 1, "HD": 2, "SD": 3}
        best_priority = 999
        for asset in assets:
            if asset.get("type") != "video":
                continue
            asset_url = asset.get("url", "")
            if not asset_url:
                continue
            flavor = asset.get("profileFlavorId", "")
            p = priority.get(flavor, 50)
            if p < best_priority:
                best_priority = p
                best_url = asset_url
        if best_url:
            print("Found video URL via __NEXT_DATA__ (Watchity CDN)", file=sys.stderr)
            return best_url

        # Fallback: try mediaItem.videos (older format)
        media_v1 = page_props.get("mediaItem", {})
        videos = media_v1.get("videos", [])
        for video in videos:
            resolutions = video.get("resolutions", [])
            for res in resolutions:
                res_url = res.get("url", "")
                if res_url:
                    print(
                        "Found video URL via __NEXT_DATA__ (legacy format)",
                        file=sys.stderr,
                    )
                    return res_url

    # Strategy 2: Look for direct .mp4 or .m3u8 URLs in the page
    if html:
        mp4_match = re.search(
            r'"(https?://cdn-mmc\.watchity\.net/[^"]*\.mp4)"',
            html,
        )
        if mp4_match:
            video_url = mp4_match.group(1)
            print("Found Watchity CDN URL in page source", file=sys.stderr)
            return video_url

    print("Could not find video URL in multimedia page.", file=sys.stderr)
    return None


def _resolve_transcript_url(url, language=None):
    """Find a transcript download URL from the EP multimedia page.

    The EP multimedia site provides official transcripts as SRT files for
    some video clips. These appear under "Related content" on the page and
    are stored in the ``__NEXT_DATA__`` JSON blob under ``pageProps``.

    The transcript URLs follow this pattern:
        https://api.multimedia.europarl.europa.eu/documents/.../<id>...[SD-<LANG>].srt?download=true

    Args:
        url: EP multimedia video clip URL.
        language: Preferred language code (e.g. 'en', 'de'). If None, returns
                  the first SRT transcript found.

    Returns:
        A transcript download URL (str), or None if no transcript is available.
    """
    if not EP_VIDEO_PATTERN.match(url):
        return None

    page_props, _ = _fetch_next_data(url)
    if not page_props:
        return None

    return _extract_transcript_url(page_props, language=language)


def _extract_transcript_url(page_props, language=None):
    """Extract transcript URL from parsed pageProps.

    Searches through relatedItems/documents/attachments in the pageProps
    for SRT transcript files.

    Args:
        page_props: Parsed pageProps dict from __NEXT_DATA__.
        language: Preferred language code (e.g. 'en', 'de').

    Returns:
        A transcript download URL, or None.
    """
    lang_upper = language.upper() if language else None

    # The EP page stores related content (transcripts, shotlists) in various
    # possible locations within pageProps. Search broadly.
    candidates = []

    # Strategy 1: Look for relatedItems / relatedContent / documents
    for key in (
        "relatedItems",
        "relatedContent",
        "documents",
        "attachments",
        "related",
    ):
        items = page_props.get(key, [])
        if isinstance(items, list):
            candidates.extend(items)

    # Strategy 2: Look inside mediaItemV2 for related content
    media_v2 = page_props.get("mediaItemV2", {})
    for key in (
        "relatedItems",
        "relatedContent",
        "documents",
        "attachments",
        "related",
    ):
        items = media_v2.get(key, [])
        if isinstance(items, list):
            candidates.extend(items)

    # Strategy 3: Recursively search pageProps for any .srt URLs
    srt_urls = _find_srt_urls(page_props)

    # Filter candidates for SRT transcript entries
    best_url = None
    for item in candidates:
        if not isinstance(item, dict):
            continue
        # Check for SRT format indicators
        item_url = item.get("url", "") or item.get("downloadUrl", "") or item.get("href", "")
        item_format = str(item.get("format", "") or item.get("mimeType", "")).lower()
        item_type = str(item.get("type", "") or item.get("category", "")).lower()

        is_srt = ".srt" in item_url.lower() or "srt" in item_format or "subrip" in item_format
        item_title = str(item.get("title", "")).lower()
        is_transcript = "transcript" in item_type or "transcript" in item_title

        if is_srt or is_transcript:
            if lang_upper and lang_upper in item_url.upper():
                return item_url  # Exact language match
            if not best_url:
                best_url = item_url

    if best_url:
        return best_url

    # Fall back to any .srt URL found in the page data
    if srt_urls:
        if lang_upper:
            for srt_url in srt_urls:
                if lang_upper in srt_url.upper():
                    return srt_url
        return srt_urls[0]

    return None


def _find_srt_urls(obj, depth=0):
    """Recursively find .srt URLs in a nested data structure."""
    if depth > 10:
        return []
    urls = []
    if isinstance(obj, str):
        if ".srt" in obj.lower() and ("http" in obj.lower() or obj.startswith("/")):
            urls.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            urls.extend(_find_srt_urls(v, depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            urls.extend(_find_srt_urls(item, depth + 1))
    return urls


def parse_srt(srt_text):
    """Parse SRT subtitle text into a list of segment dicts.

    Args:
        srt_text: Raw SRT file content.

    Returns:
        List of dicts with keys: start (float seconds), end (float seconds),
        text (str).
    """
    segments = []
    blocks = re.split(r"\n\s*\n", srt_text.strip())
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue
        # Find the timestamp line (contains " --> ")
        ts_line = None
        text_start = 0
        for i, line in enumerate(lines):
            if " --> " in line:
                ts_line = line
                text_start = i + 1
                break
        if not ts_line:
            continue
        parts = ts_line.split(" --> ")
        if len(parts) != 2:
            continue
        start = _parse_srt_timestamp(parts[0].strip())
        end = _parse_srt_timestamp(parts[1].strip())
        if start is None or end is None:
            continue
        text = " ".join(line.strip() for line in lines[text_start:] if line.strip())
        # Decode HTML entities (EP transcripts contain &amp;, &#321;, etc.)
        text = html_mod.unescape(text)
        if text:
            segments.append({"start": start, "end": end, "text": text})
    return segments


def _parse_srt_timestamp(ts):
    """Parse an SRT timestamp like '00:01:23,456' into seconds (float)."""
    # Accept both comma and dot as decimal separator
    ts = ts.replace(",", ".")
    match = re.match(r"(\d+):(\d+):(\d+)\.(\d+)", ts)
    if not match:
        # Try without milliseconds
        match = re.match(r"(\d+):(\d+):(\d+)", ts)
        if not match:
            return None
        h, m, s = match.groups()
        return int(h) * 3600 + int(m) * 60 + int(s)
    h, m, s, ms = match.groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000


def parse_chapter_speaker(text):
    """Extract speaker name from an EP chapter/shotlist entry.

    EP chapter SRT entries have this format:
        ``SOUNDBITE (Original), Deirdre CLUNE (EPP, IE), -``
        ``SOUNDBITE (Original), Sergey LAGODINSKY (Greens/EFA, DE), -``
        ``End``

    Args:
        text: The text content of a chapter SRT segment.

    Returns:
        Speaker name (str) or None if not a SOUNDBITE entry.
    """
    # Match: SOUNDBITE (...), <Speaker Name> (<Group>, <Country>)
    match = re.match(
        r"SOUNDBITE\s*\([^)]*\),\s*(.+?)\s*\([^)]+,\s*[A-Z]{2}\)",
        text,
    )
    if match:
        return match.group(1).strip()
    return None


def download_chapters(url, language=None):
    """Download the EP chapter/shotlist SRT for a video clip URL.

    The EP multimedia site provides chapter lists as SRT files. These
    contain speaker names and timestamps but not the spoken words.

    Args:
        url: EP multimedia video clip URL.
        language: Preferred language (e.g. 'en').

    Returns:
        List of segment dicts (start, end, text), or None if not available.
    """
    print("Looking for EP chapter data...", file=sys.stderr)

    transcript_url = _resolve_transcript_url(url, language=language)
    if not transcript_url:
        print("No chapter data found on EP multimedia page.", file=sys.stderr)
        return None

    # Make relative URLs absolute
    if transcript_url.startswith("/"):
        transcript_url = EP_MULTIMEDIA_API_URL + transcript_url

    print(f"Downloading chapters from: {transcript_url[:100]}...", file=sys.stderr)
    try:
        resp = requests.get(
            transcript_url,
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
        print(f"Could not download chapters: {e}", file=sys.stderr)
        return None

    segments = parse_srt(resp.text)
    if segments:
        print(f"Downloaded chapters: {len(segments)} entries", file=sys.stderr)
    else:
        print("Chapter data downloaded but could not be parsed.", file=sys.stderr)
        return None

    return segments


def merge_speakers_into_segments(whisper_segments, chapter_segments):
    """Merge speaker names from EP chapters into Whisper transcription segments.

    For each Whisper segment, finds the chapter entry whose time range
    contains the segment's start time, extracts the speaker name, and
    adds it as a ``speaker`` field.

    Args:
        whisper_segments: List of segment dicts from Whisper (start, end, text).
        chapter_segments: List of chapter dicts from EP SRT (start, end, text).

    Returns:
        The whisper_segments list with ``speaker`` fields added where possible.
    """
    if not chapter_segments:
        return whisper_segments

    # Build speaker timeline: list of (start, end, speaker_name)
    speaker_ranges = []
    for i, ch in enumerate(chapter_segments):
        speaker = parse_chapter_speaker(ch["text"])
        if not speaker:
            continue
        # Chapter end time: use the next chapter's start, or this chapter's end
        if i + 1 < len(chapter_segments):
            end = chapter_segments[i + 1]["start"]
        else:
            end = ch["end"]
        speaker_ranges.append((ch["start"], end, speaker))

    if not speaker_ranges:
        return whisper_segments

    for seg in whisper_segments:
        seg_mid = (seg["start"] + seg["end"]) / 2
        for rng_start, rng_end, speaker in speaker_ranges:
            if rng_start <= seg_mid < rng_end:
                seg["speaker"] = speaker
                break

    return whisper_segments


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
            else:
                print("Falling back to yt-dlp extractor.", file=sys.stderr)
        else:
            print("Falling back to yt-dlp extractor.", file=sys.stderr)

    # For direct MP4 URLs (e.g. Watchity CDN video clips), download with ffmpeg
    if download_url != url and not resolved_hls and download_url.endswith(".mp4"):
        wav_path = output_dir / f"{meeting_ref}.wav"
        try:
            import subprocess

            print(
                "Downloading video clip with ffmpeg (converting to WAV)...",
                file=sys.stderr,
            )
            ffmpeg_cmd = [
                "ffmpeg",
                "-y",
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
            result = subprocess.run(
                ffmpeg_cmd,
                stdin=subprocess.DEVNULL,
                timeout=7200,
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
