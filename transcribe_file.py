#!/usr/bin/env python3
"""Transcribe a local audio/video file using faster-whisper.

Usage:
    python transcribe_file.py recording.mp4
    python transcribe_file.py recording.mp4 --model small --language en
    python transcribe_file.py recording.mp4 --format srt -o transcript.srt
    python transcribe_file.py recording.mp4 --format docx -o transcript.docx
    python transcribe_file.py recording.mp4 --clean

Supports any format ffmpeg can read (mp4, mkv, webm, wav, mp3, m4a, ...).
For video files, audio is extracted automatically via ffmpeg.
"""

import argparse
import os
import subprocess
import sys
import tempfile


def extract_audio(input_path):
    """Extract audio from a video/audio file to 16kHz mono WAV via ffmpeg."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    import shutil

    ffmpeg_cmd = shutil.which("ffmpeg")
    if ffmpeg_cmd is None:
        # Common Windows install location
        candidate = r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"
        if os.path.isfile(candidate):
            ffmpeg_cmd = candidate
        else:
            print("Error: ffmpeg not found. Install it or add it to PATH.", file=sys.stderr)
            sys.exit(1)
    cmd = [
        ffmpeg_cmd, "-y", "-i", input_path,
        "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        tmp.name,
    ]
    print(f"Extracting audio to WAV...", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ffmpeg error: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return tmp.name


def main():
    parser = argparse.ArgumentParser(
        description="Transcribe a local audio/video file using faster-whisper.",
    )
    parser.add_argument("file", help="Path to audio or video file")
    parser.add_argument(
        "-o", "--output", help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--model", default="base",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Whisper model size (default: base)",
    )
    parser.add_argument(
        "--language", default=None,
        help="Language code, e.g. 'en', 'de' (default: auto-detect)",
    )
    parser.add_argument(
        "--task", default="transcribe", choices=["transcribe", "translate"],
        help="'transcribe' keeps original language, 'translate' translates to English",
    )
    parser.add_argument(
        "--format", default="txt", choices=["txt", "srt", "vtt", "md", "docx"],
        help="Output format (default: txt). docx requires -o.",
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Remove filler words and repetitions",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print(f"Error: file not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    # Reuse the project's transcriber and formatters
    from video_transcriber.transcriber import transcribe_audio
    from video_transcriber.cli import format_segments, write_docx, _unique_path

    # Extract audio to WAV if not already a WAV file
    if args.file.lower().endswith(".wav"):
        audio_path = args.file
        cleanup = False
    else:
        audio_path = extract_audio(args.file)
        cleanup = True

    try:
        print(
            f"Transcribing '{args.file}' with model '{args.model}' "
            f"(language={args.language or 'auto'})...",
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
    finally:
        if cleanup:
            try:
                os.unlink(audio_path)
            except OSError:
                pass

    if args.clean:
        from video_transcriber.postprocess import clean_segments
        segments = clean_segments(segments)

    # Output
    if args.format == "docx":
        if not args.output:
            print("Error: --format docx requires -o <file.docx>", file=sys.stderr)
            sys.exit(1)
        out_path = _unique_path(args.output)
        write_docx(segments, out_path)
        print(f"Transcript written to: {out_path}", file=sys.stderr)
    else:
        output = format_segments(segments, args.format)
        if args.output:
            out_path = _unique_path(args.output)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"Transcript written to: {out_path}", file=sys.stderr)
        else:
            print(output)


if __name__ == "__main__":
    main()
