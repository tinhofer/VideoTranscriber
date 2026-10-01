# CLAUDE.md

## Project Overview

**video-transcriber** — CLI tool that transcribes videos from any yt-dlp-supported URL (YouTube, Vimeo, etc.) as well as European Parliament webstreaming videos with multi-track support. Pipeline: download audio → transcribe with Whisper → detect languages → merge interpreter tracks → post-process → format output.

## Quick Reference

```bash
# Install (dev)
pip install -e ".[dev]"

# Easy mode (Windows): double-click transcribe.bat — interactive prompts for URL, format, model

# Run on any URL (YouTube, Vimeo, etc.)
video-transcriber https://www.youtube.com/watch?v=VIDEO_ID
video-transcriber https://vimeo.com/123456789 --model small --format docx -o transcript.docx

# Run on EP URL (simple mode — single track, legacy behavior)
video-transcriber <EP_URL>
video-transcriber <EP_URL> -o out.srt --format srt --model small --language en

# Run (auto mode — multi-language: EN/DE original, other languages via DE interpreter)
video-transcriber <EP_URL> --mode auto --model large-v3

# Run with filler/repetition cleanup
video-transcriber <EP_URL> --clean

# Export to Word document
video-transcriber <EP_URL> --format docx -o transcript.docx

# Select specific audio track (e.g. DE interpreter channel)
video-transcriber <EP_URL> --audio-track de

# Transcribe with speaker names from EP chapter data (video clips only)
video-transcriber <EP_VIDEO_URL> --transcript --model small

# Tests (use python -m pytest, not bare pytest)
python -m pytest

# Lint
ruff check src/ tests/
ruff format --check src/ tests/
```

## Project Structure

```
src/video_transcriber/
├── cli.py           # Argument parsing, output formatting (txt/srt/vtt/md/docx), main() orchestration
├── downloader.py    # EP stream resolution (glcloud API + Watchity CDN), ffmpeg/yt-dlp audio download → 16kHz mono WAV, EP chapter/speaker download + SRT parsing
├── transcriber.py   # faster-whisper transcription with CUDA fallback, VAD, per-segment language detection
├── postprocess.py   # Filler word removal (DE+EN) and consecutive repetition cleanup
├── pipeline.py      # Multi-track orchestration: original floor + DE interpreter merging
├── __init__.py      # Package version
└── __main__.py      # python -m entry point

transcribe.bat           # Interactive Windows batch script (prompts for URL, format, model)

tests/
├── test_cli.py          # Timestamp formatting, argument parsing, output format tests
├── test_downloader.py   # Meeting reference extraction, SRT parsing, speaker extraction, merge tests
├── test_pipeline.py     # Interpreter segment matching and collection tests
└── test_postprocess.py  # Filler removal, repetition cleanup, segment cleaning tests
```

## Architecture

1. **Download** (`downloader.py`): Accepts any yt-dlp-supported URL (YouTube, Vimeo, etc.) as well as EP URLs. For generic URLs, yt-dlp handles download directly (extracting video title for the filename). For EP URLs, two resolution paths: **Webstreaming** URLs resolve HLS streams from EP's glcloud API (`control.eup.glcloud.eu`). **Player clip links** (`control.eup.glcloud.eu/content-manager/content-page/<EVENT-ID>?audio=..&start=<unix>&end=<unix>`) use the same glcloud path, but the URL's `start`/`end` override the event's startTime/endTime so only the clip is downloaded, and `audio=` preselects the audio track. **Video clip** URLs (e.g. `_I242316`) are resolved by scraping the EP multimedia page (a Next.js app) and extracting direct MP4 URLs from the `__NEXT_DATA__` JSON blob — these are hosted on Watchity CDN (`cdn-mmc.watchity.net`). Downloads via direct ffmpeg (preferred) or yt-dlp fallback. Outputs 16kHz mono WAV for Whisper compatibility. Supports `audio_track` parameter to select EP interpreter channels (`'or'` = original floor, `'de'`/`'en'`/`'fr'` = interpreter). For webstreaming, the glcloud API `audio` parameter is sent, but the actual track is then re-selected from the HLS master manifest by metadata (`_refine_hls_audio_url()`): the API's fixed channel mapping resolves to a silent channel for some events (observed with `or` → channel-04-bxl on 20260714-1515-COMMITTEE-IMCO), so `#EXT-X-MEDIA:TYPE=AUDIO` renditions are matched via NAME/LANGUAGE attributes (floor aliases: or/qaa/original/floor; languages by code, ISO 639-2, prefix, or full English name). If the manifest has no renditions or no match, the API-resolved URL is used unchanged. After every EP download a silence check runs (`_check_audio_silence()`, ffmpeg volumedetect): mean_volume below -60 dB raises an error asking the user to pick a different `--audio-track`. For video clips, ffmpeg selects the matching audio stream by ISO 639-2 language metadata (e.g. `--audio-track de` maps to stream language `ger`).
2. **Transcribe** (`transcriber.py`): Loads faster-whisper model, probes CUDA availability via ctranslate2, falls back to CPU int8. Uses beam_size=5, VAD filter, and `condition_on_previous_text=False` for verbatim accuracy. Per-segment language detection via `lingua-language-detector`.
3. **Post-process** (`postprocess.py`): Regex-based removal of filler words (DE: ähm, äh, naja, sozusagen, quasi; EN: um, uh, you know, I mean, etc.) and consecutive phrase repetitions. Activated via `--clean` flag or automatically in `--mode auto`.
4. **Pipeline** (`pipeline.py`): Multi-language workflow for `--mode auto`. Downloads original floor audio, transcribes with auto-detection, identifies non-EN/DE segments via lingua, downloads DE interpreter track for those time ranges, merges results.
5. **Format & Output** (`cli.py`): Formats segments as plain text (with timestamps and language tags), SRT, WebVTT, Markdown, or Word (.docx). Writes to stdout or file. Three modes: `simple` (legacy single-track), `auto` (multi-language pipeline), and `--transcript` (Whisper + EP speaker names). Speaker names appear as `[Speaker Name]` tags in txt/srt/vtt and as bold headings in md/docx. The md and docx formats show video duration at the top instead of per-segment timestamps.
6. **EP Chapters** (`downloader.py`): The EP multimedia site provides chapter/shotlist SRT files for video clips under "Related content". These contain speaker names and timestamps (not spoken words). The `--transcript` flag downloads these, runs Whisper for the actual words, then merges speaker names into the Whisper output using time-range matching. Chapter URLs are found in the `__NEXT_DATA__` JSON blob. HTML entities in chapter text are decoded automatically.

## CLI Options

| Option | Description |
|---|---|
| `--mode simple\|auto` | `simple`: single-track (default). `auto`: multi-language pipeline (EN/DE original + DE interpreter) |
| `--clean` | Remove filler words and repetitions |
| `--audio-track <code>` | Select audio track: `or` (original floor), `de`/`en`/`fr`/... (interpreter) |
| `--model <size>` | Whisper model: tiny, base (default), small, medium, large-v3 |
| `--language <code>` | Force language (default: auto-detect) |
| `--format txt\|srt\|vtt\|md\|docx` | Output format (default: txt). md and docx show duration instead of per-segment timestamps. docx requires `-o`. |
| `-o <path>` | Output file (default: stdout) |
| `--transcript` | Enrich Whisper output with speaker names from EP chapter data (video clips only) |
| `--keep-audio` | Keep downloaded audio after transcription |
| `--audio-dir <dir>` | Directory for audio files (default: temp) |

## Dependencies

- **yt-dlp** — audio download fallback
- **faster-whisper** — speech-to-text (wraps ctranslate2)
- **requests** — HTTP for EP glcloud API
- **tqdm** — transcription progress bar
- **lingua-language-detector** — per-segment language detection
- **python-docx** — Word document output
- **ffmpeg** — system dependency, must be on PATH

## Key Details

- Python >=3.10, MIT license
- Entry point: `video-transcriber` → `video_transcriber.cli:main`
- Ruff config: line-length=100, rules E/F/W/I
- All user-facing status goes to stderr; transcript output goes to stdout (allows piping)
- Empty transcriptions are an error: if Whisper returns 0 segments, the CLI prints "No speech recognized — probably a wrong or silent audio track" and exits 1 instead of writing an empty document (`_output_results()` in cli.py). transcribe.bat checks the exit code and shows an ERROR banner instead of "Done!".
- Output files are auto-numbered to avoid overwriting: if `transcript.docx` exists, the next becomes `transcript_2.docx`, `transcript_3.docx`, etc. Applies to all formats with `-o`.
- Supported URL formats:
  - Any yt-dlp-supported URL (YouTube, Vimeo, etc.)
  - EP Webstreaming: `https://multimedia.europarl.europa.eu/en/webstreaming/committees_20260317-1430-COMMITTEE-EMPL`
  - EP Streaming links: `https://www.europarl.europa.eu/streaming/?event=20260709-1400-SPECIAL-OTHER` (normalized to the multimedia webstreaming URL via `normalize_ep_url()`)
  - EP Video clips: `https://multimedia.europarl.europa.eu/en/video/some-title_I242316`
  - EP Player clip links ("share clip" from the embedded player): `https://control.eup.glcloud.eu/content-manager/content-page/20260714-1515-COMMITTEE-IMCO?audio=en&start=1784035974&end=1784039247&lang=en` — `start`/`end` (Unix timestamps) limit the download to the clip instead of the whole sitting; `audio=<lang>` preselects the audio track (an explicit `--audio-track` still wins). Parsed by `parse_glcloud_url()`; the clip range is forwarded to the content-page request and forced onto the HLS URL as `startTime`/`endTime` (even for finalVod streams).
- EP-specific features (`--mode auto`, `--transcript`, `--audio-track`) only work with EP URLs
- The glcloud API replaced the older connectedviews.eu infrastructure in early 2025
- EP audio tracks: The glcloud API `audio` parameter selects interpreter channels; the EP website shows these under "Select Audio Track"
- glcloud bot protection (observed 2026-10): the content page sits behind Akamai and answers 403 "Access Denied" unless the request looks like a browser page load — full Chrome User-Agent, `Accept-Language` and the `Sec-Fetch-*` headers are all required (`GLCLOUD_PAGE_HEADERS` in downloader.py). The media host (`live.media`/`vod.media.eup.glcloud.eu`) only needs the Referer. The EP multimedia site itself answers scripts with an AWS WAF JavaScript challenge (HTTP 202, empty body), which is why the yt-dlp fallback fails with "Unable to extract next.js data" — a 403 from glcloud is the real error to look at.
- Live-archive manifests (same-day recordings, `master-archive.m3u8`, `finalVod: false`) only number their audio renditions (`NAME="audio01"`..`"audio32"`, private-use LANGUAGE codes like `qbf`), and the DEFAULT rendition can be silent. The track order comes from `languageMapping` in the content page's ng-state: entry N (1-based) ↔ `audioNN` (OR=audio01, EN=audio02, FR=audio03, DE=audio04, ...). `_select_numbered_rendition()` handles this and takes precedence over NAME/LANGUAGE matching, because the codes are meaningless there (`qaa` is *not* the floor in these manifests).
- Video clips vs webstreaming: Two different hosting backends. Webstreaming events use glcloud HLS streams. Video clips (archived content with `/video/..._I<id>` URLs) use Watchity CDN with direct MP4 files — the glcloud API returns 404 for these. The EP multimedia site is a Next.js app; video clip metadata (including MP4 URLs at multiple quality levels: ORIGINAL, FHD, HD, SD) is embedded in `<script id="__NEXT_DATA__">` under `pageProps.mediaItemV2.mediaAssets`.
