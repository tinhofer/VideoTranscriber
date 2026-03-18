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
    # Check if CUDA libraries are actually usable before attempting GPU mode.
    # faster-whisper uses ctranslate2 which needs cuBLAS/cuDNN DLLs at load time.
    _use_gpu = False
    try:
        import ctranslate2

        if "cuda" in ctranslate2.get_supported_compute_types("cuda"):
            _use_gpu = True
    except Exception:
        pass

    if _use_gpu:
        model = WhisperModel(model_size, device="cuda", compute_type="float16")
    else:
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
