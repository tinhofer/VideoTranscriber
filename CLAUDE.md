# CLAUDE.md

## Project Overview

**video-transcriber** — CLI tool that transcribes European Parliament webstreaming videos and video clips. Multi-stage pipeline: download audio → transcribe with Whisper → detect languages → merge interpreter tracks → post-process → format output.

## Quick Reference

```bash
# Install (dev)
pip install -e ".[dev]"

# Easy mode (Windows): double-click transcribe.bat — interactive prompts for URL, format, model

# Run (simple mode — single track, legacy behavior)
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

# Tests (use python -m pytest, not bare pytest)
python -m pytest

# Lint
ruff check src/ tests/
ruff format --check src/ tests/
```

## Project Structure

```
src/video_transcriber/
├── cli.py           # Argument parsing, output formatting (txt/srt/vtt/docx), main() orchestration
├── downloader.py    # EP stream resolution (glcloud API + Watchity CDN), ffmpeg/yt-dlp audio download → 16kHz mono WAV
├── transcriber.py   # faster-whisper transcription with CUDA fallback, VAD, per-segment language detection
├── postprocess.py   # Filler word removal (DE+EN) and consecutive repetition cleanup
├── pipeline.py      # Multi-track orchestration: original floor + DE interpreter merging
├── __init__.py      # Package version
└── __main__.py      # python -m entry point

transcribe.bat           # Interactive Windows batch script (prompts for URL, format, model)

tests/
├── test_cli.py          # Timestamp formatting, argument parsing, output format tests
├── test_downloader.py   # Meeting reference and video clip ID extraction tests
├── test_pipeline.py     # Interpreter segment matching and collection tests
└── test_postprocess.py  # Filler removal, repetition cleanup, segment cleaning tests
```

## Architecture

1. **Download** (`downloader.py`): Accepts both `/webstreaming/` and `/video/` EP URLs. Two resolution paths: **Webstreaming** URLs resolve HLS streams from EP's glcloud API (`control.eup.glcloud.eu`). **Video clip** URLs (e.g. `_I242316`) are resolved by scraping the EP multimedia page (a Next.js app) and extracting direct MP4 URLs from the `__NEXT_DATA__` JSON blob — these are hosted on Watchity CDN (`cdn-mmc.watchity.net`). Downloads via direct ffmpeg (preferred) or yt-dlp fallback. Outputs 16kHz mono WAV for Whisper compatibility. Supports `audio_track` parameter to select EP interpreter channels (`'or'` = original floor, `'de'`/`'en'`/`'fr'` = interpreter). Note: `audio_track` only applies to webstreaming URLs; video clips have a single audio track.
2. **Transcribe** (`transcriber.py`): Loads faster-whisper model, probes CUDA availability via ctranslate2, falls back to CPU int8. Uses beam_size=5, VAD filter, and `condition_on_previous_text=False` for verbatim accuracy. Per-segment language detection via `lingua-language-detector`.
3. **Post-process** (`postprocess.py`): Regex-based removal of filler words (DE: ähm, äh, naja, sozusagen, quasi; EN: um, uh, you know, I mean, etc.) and consecutive phrase repetitions. Activated via `--clean` flag or automatically in `--mode auto`.
4. **Pipeline** (`pipeline.py`): Multi-language workflow for `--mode auto`. Downloads original floor audio, transcribes with auto-detection, identifies non-EN/DE segments via lingua, downloads DE interpreter track for those time ranges, merges results.
5. **Format & Output** (`cli.py`): Formats segments as plain text (with timestamps and language tags), SRT, WebVTT, or Word (.docx). Writes to stdout or file. Two modes: `simple` (legacy single-track) and `auto` (multi-language pipeline). The docx format shows video duration at the top instead of per-segment timestamps.

## CLI Options

| Option | Description |
|---|---|
| `--mode simple\|auto` | `simple`: single-track (default). `auto`: multi-language pipeline (EN/DE original + DE interpreter) |
| `--clean` | Remove filler words and repetitions |
| `--audio-track <code>` | Select audio track: `or` (original floor), `de`/`en`/`fr`/... (interpreter) |
| `--model <size>` | Whisper model: tiny, base (default), small, medium, large-v3 |
| `--language <code>` | Force language (default: auto-detect) |
| `--format txt\|srt\|vtt\|docx` | Output format (default: txt). docx requires `-o` and shows duration instead of timestamps |
| `-o <path>` | Output file (default: stdout) |
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
- Supported EP URL formats:
  - Webstreaming: `https://multimedia.europarl.europa.eu/en/webstreaming/committees_20260317-1430-COMMITTEE-EMPL`
  - Video clips: `https://multimedia.europarl.europa.eu/en/video/some-title_I242316`
- The glcloud API replaced the older connectedviews.eu infrastructure in early 2025
- EP audio tracks: The glcloud API `audio` parameter selects interpreter channels; the EP website shows these under "Select Audio Track"
- Video clips vs webstreaming: Two different hosting backends. Webstreaming events use glcloud HLS streams. Video clips (archived content with `/video/..._I<id>` URLs) use Watchity CDN with direct MP4 files — the glcloud API returns 404 for these. The EP multimedia site is a Next.js app; video clip metadata (including MP4 URLs at multiple quality levels: ORIGINAL, FHD, HD, SD) is embedded in `<script id="__NEXT_DATA__">` under `pageProps.mediaItemV2.mediaAssets`.
