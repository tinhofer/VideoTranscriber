# CLAUDE.md

## Project Overview

**video-transcriber** — CLI tool that transcribes European Parliament webstreaming videos. Three-stage pipeline: download audio → transcribe with Whisper → format output.

## Quick Reference

```bash
# Install (dev)
pip install -e ".[dev]"

# Run
video-transcriber <EP_URL>
video-transcriber <EP_URL> -o out.srt --format srt --model small --language en

# Tests
pytest

# Lint
ruff check src/ tests/
ruff format --check src/ tests/
```

## Project Structure

```
src/video_transcriber/
├── cli.py          # Argument parsing, output formatting (txt/srt/vtt), main() orchestration
├── downloader.py   # EP glcloud API resolution, ffmpeg/yt-dlp audio download → 16kHz mono WAV
├── transcriber.py  # faster-whisper transcription with CUDA fallback, VAD, tqdm progress bar
├── __init__.py     # Package version
└── __main__.py     # python -m entry point

tests/
├── test_cli.py         # Timestamp formatting, argument parsing, output format tests
└── test_downloader.py  # Meeting reference extraction tests
```

## Architecture

1. **Download** (`downloader.py`): Resolves HLS stream from EP's glcloud API (`control.eup.glcloud.eu`), downloads via direct ffmpeg (preferred) or yt-dlp fallback. Outputs 16kHz mono WAV for Whisper compatibility.
2. **Transcribe** (`transcriber.py`): Loads faster-whisper model, probes CUDA availability via ctranslate2, falls back to CPU int8. Uses beam_size=5 and VAD filter. Shows tqdm progress bar based on audio duration.
3. **Format & Output** (`cli.py`): Formats segments as plain text (with timestamps), SRT, or WebVTT. Writes to stdout or file. Auto-cleans temp audio unless `--keep-audio` or `--audio-dir`.

## Dependencies

- **yt-dlp** — audio download fallback
- **faster-whisper** — speech-to-text (wraps ctranslate2)
- **requests** — HTTP for EP glcloud API
- **tqdm** — transcription progress bar
- **ffmpeg** — system dependency, must be on PATH

## Key Details

- Python >=3.10, MIT license
- Entry point: `video-transcriber` → `video_transcriber.cli:main`
- Ruff config: line-length=100, rules E/F/W/I
- All user-facing status goes to stderr; transcript output goes to stdout (allows piping)
- EP URL pattern: `https://multimedia.europarl.europa.eu/en/webstreaming/<meeting-ref>`
- The glcloud API replaced the older connectedviews.eu infrastructure in early 2025
