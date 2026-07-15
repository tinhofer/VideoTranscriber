# Video Transcriber

Transcribe videos using [faster-whisper](https://github.com/SYSTRAN/faster-whisper). Supports any URL that [yt-dlp](https://github.com/yt-dlp/yt-dlp) can handle (YouTube, Vimeo, etc.) as well as European Parliament webstreaming URLs with multi-track and speaker-name features.

## Installation

```bash
# Install ffmpeg (required by yt-dlp for audio extraction)
sudo apt install ffmpeg

# Install the package
pip install -e .
```

## Usage

```bash
# Any video URL (YouTube, Vimeo, etc.)
video-transcriber https://www.youtube.com/watch?v=dQw4w9WgXcQ -o transcript.txt
video-transcriber https://vimeo.com/123456789 --model small --format docx -o transcript.docx

# European Parliament webstreaming
video-transcriber https://multimedia.europarl.europa.eu/en/webstreaming/committees_20260317-1430-COMMITTEE-EMPL

# Save to file with timestamps
video-transcriber URL -o transcript.txt

# Use a larger model for better accuracy
video-transcriber URL --model large-v3 -o transcript.txt

# Specify language explicitly
video-transcriber URL --language en

# Translate to English
video-transcriber URL --task translate -o translated.txt

# Generate SRT subtitles
video-transcriber URL --format srt -o subtitles.srt

# Generate WebVTT subtitles
video-transcriber URL --format vtt -o subtitles.vtt

# Keep downloaded audio
video-transcriber URL --keep-audio --audio-dir ./audio
```

## Options

| Option | Description |
|---|---|
| `url` | Video URL (YouTube, Vimeo, EP webstreaming, or any yt-dlp-supported site) |
| `-o, --output` | Output file (default: stdout) |
| `--model` | Whisper model: `tiny`, `base`, `small`, `medium`, `large-v3` |
| `--language` | Language code, e.g. `en`, `fr`, `de` (default: auto-detect) |
| `--task` | `transcribe` or `translate` (to English) |
| `--format` | `txt`, `srt`, or `vtt` |
| `--audio-dir` | Directory for downloaded audio |
| `--keep-audio` | Don't delete audio after transcription |

## How it works

1. **Download** — Uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) to extract audio from any supported video URL. For EP webstreaming URLs, resolves HLS streams via the glcloud API.
2. **Transcribe** — Uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2 backend) for speech-to-text with automatic language detection
3. **Format** — Outputs timestamped text, SRT, or WebVTT subtitles
