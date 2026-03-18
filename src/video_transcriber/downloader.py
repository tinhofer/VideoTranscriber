"""Download audio from European Parliament webstreaming URLs."""

import re
import tempfile
from pathlib import Path

import yt_dlp


EP_URL_PATTERN = re.compile(
    r"https?://(?:multimedia\.europarl\.europa\.eu/\w+/webstreaming/"
    r"|webstreaming\.europarl\.europa\.eu/)"
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


def download_audio(url, output_dir=None):
    """Download audio from an EP webstreaming URL using yt-dlp.

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
        ydl.download([url])

    wav_path = output_dir / f"{meeting_ref}.wav"
    if wav_path.exists():
        return str(wav_path)

    # yt-dlp may append different extensions; find the output file
    for f in output_dir.iterdir():
        if f.stem == meeting_ref:
            return str(f)

    raise FileNotFoundError(
        f"Downloaded audio not found in {output_dir}. "
        "yt-dlp may not support this URL format."
    )
