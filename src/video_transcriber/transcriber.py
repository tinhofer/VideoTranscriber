"""Transcribe audio using faster-whisper."""

from faster_whisper import WhisperModel


def transcribe_audio(audio_path, model_size="base", language=None, task="transcribe"):
    """Transcribe an audio file using faster-whisper.

    Args:
        audio_path: Path to the audio file.
        model_size: Whisper model size (tiny, base, small, medium, large-v3).
        language: Language code (e.g. 'en', 'fr'). None for auto-detection.
        task: 'transcribe' or 'translate' (translate to English).

    Returns:
        List of dicts with keys: start, end, text.
    """
    try:
        model = WhisperModel(model_size, device="auto", compute_type="auto")
    except Exception:
        # CUDA not available — fall back to CPU
        import sys

        print("CUDA not available, using CPU for transcription.", file=sys.stderr)
        model = WhisperModel(model_size, device="cpu", compute_type="int8")

    segments_iter, info = model.transcribe(
        audio_path,
        language=language,
        task=task,
        beam_size=5,
        vad_filter=True,
    )

    if language is None:
        import sys

        print(
            f"Detected language: {info.language} (probability: {info.language_probability:.2f})",
            file=sys.stderr,
        )

    segments = []
    for segment in segments_iter:
        segments.append(
            {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
            }
        )

    return segments
