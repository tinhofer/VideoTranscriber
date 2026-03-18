"""CLI interface for video-transcriber."""

import argparse
import sys

from video_transcriber.downloader import download_audio
from video_transcriber.transcriber import transcribe_audio


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="video-transcriber",
        description="Transcribe European Parliament webstreaming videos.",
    )
    parser.add_argument(
        "url",
        help=(
            "EP webstreaming URL, e.g. "
            "https://multimedia.europarl.europa.eu/en/webstreaming/"
            "committees_20260317-1430-COMMITTEE-EMPL"
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output file path for the transcript (default: stdout)",
    )
    parser.add_argument(
        "--model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Whisper model size (default: base)",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Language code for transcription, e.g. 'en', 'fr', 'de' (default: auto-detect)",
    )
    parser.add_argument(
        "--task",
        default="transcribe",
        choices=["transcribe", "translate"],
        help="Task: 'transcribe' keeps original language, 'translate' translates to English",
    )
    parser.add_argument(
        "--format",
        default="txt",
        choices=["txt", "srt", "vtt"],
        help="Output format (default: txt)",
    )
    parser.add_argument(
        "--audio-dir",
        default=None,
        help="Directory to store downloaded audio (default: temp directory)",
    )
    parser.add_argument(
        "--keep-audio",
        action="store_true",
        help="Keep the downloaded audio file after transcription",
    )
    return parser.parse_args(argv)


def format_timestamp(seconds):
    """Convert seconds to HH:MM:SS,mmm format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_timestamp_vtt(seconds):
    """Convert seconds to HH:MM:SS.mmm format (VTT uses dot not comma)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def format_segments(segments, fmt):
    """Format transcription segments into the requested output format."""
    lines = []
    if fmt == "txt":
        for segment in segments:
            ts = format_timestamp(segment["start"]).split(",")[0]
            lines.append(f"[{ts}] {segment['text'].strip()}")
    elif fmt == "srt":
        for i, segment in enumerate(segments, 1):
            start = format_timestamp(segment["start"])
            end = format_timestamp(segment["end"])
            lines.append(str(i))
            lines.append(f"{start} --> {end}")
            lines.append(segment["text"].strip())
            lines.append("")
    elif fmt == "vtt":
        lines.append("WEBVTT")
        lines.append("")
        for segment in segments:
            start = format_timestamp_vtt(segment["start"])
            end = format_timestamp_vtt(segment["end"])
            lines.append(f"{start} --> {end}")
            lines.append(segment["text"].strip())
            lines.append("")
    return "\n".join(lines)


def main(argv=None):
    args = parse_args(argv)

    try:
        print(f"Downloading audio from: {args.url}", file=sys.stderr)
        audio_path = download_audio(args.url, output_dir=args.audio_dir)
        print(f"Audio saved to: {audio_path}", file=sys.stderr)
    except Exception as e:
        print(f"Error downloading audio: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        print(
            f"Transcribing with model '{args.model}' (language={args.language or 'auto'})...",
            file=sys.stderr,
        )
        segments = transcribe_audio(
            audio_path,
            model_size=args.model,
            language=args.language,
            task=args.task,
        )
    except Exception as e:
        print(f"Error during transcription: {e}", file=sys.stderr)
        sys.exit(1)

    output = format_segments(segments, args.format)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Transcript written to: {args.output}", file=sys.stderr)
    else:
        print(output)

    if not args.keep_audio and not args.audio_dir:
        import os

        try:
            os.unlink(audio_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
