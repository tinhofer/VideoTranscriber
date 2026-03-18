"""Transcribe audio using faster-whisper."""

import sys

from faster_whisper import WhisperModel
from tqdm import tqdm


def _get_device_and_compute():
    """Determine the best device and compute type for faster-whisper."""
    try:
        import ctranslate2

        if "cuda" in ctranslate2.get_supported_compute_types("cuda"):
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def transcribe_audio(
    audio_path,
    model_size="base",
    language=None,
    task="transcribe",
    word_timestamps=False,
):
    """Transcribe an audio file using faster-whisper.

    Args:
        audio_path: Path to the audio file.
        model_size: Whisper model size (tiny, base, small, medium, large-v3).
        language: Language code (e.g. 'en', 'fr'). None for auto-detection.
        task: 'transcribe' or 'translate' (translate to English).
        word_timestamps: Whether to include word-level timestamps.

    Returns:
        List of dicts with keys: start, end, text, language (if detected).
    """
    device, compute_type = _get_device_and_compute()
    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    segments_iter, info = model.transcribe(
        audio_path,
        language=language,
        task=task,
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=False,
        word_timestamps=word_timestamps,
    )

    detected_language = None
    if language is None:
        detected_language = info.language
        print(
            f"Detected language: {info.language} (probability: {info.language_probability:.2f})",
            file=sys.stderr,
        )

    duration = info.duration
    segments = []
    with tqdm(
        total=duration,
        unit="s",
        desc="Transcribing",
        file=sys.stderr,
        bar_format="{desc}: {percentage:3.0f}%|{bar}| {n:.0f}/{total:.0f}s [{elapsed}<{remaining}]",
    ) as pbar:
        for segment in segments_iter:
            seg_dict = {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
            }
            if detected_language:
                seg_dict["language"] = detected_language
            segments.append(seg_dict)
            pbar.update(segment.end - pbar.n)

    return segments


def detect_segment_languages(segments):
    """Detect language per segment using langdetect.

    Adds or updates the 'language' key on each segment dict.
    Returns the modified segments list.
    """
    from lingua import LanguageDetectorBuilder

    detector = LanguageDetectorBuilder.from_all_languages().build()

    for seg in segments:
        text = seg["text"].strip()
        if len(text) < 10:
            # Too short for reliable detection; keep existing or mark unknown
            seg.setdefault("language", "unknown")
            continue
        result = detector.detect_language_of(text)
        if result is not None:
            seg["language"] = result.iso_code_639_1.name.lower()
        else:
            seg.setdefault("language", "unknown")
    return segments
