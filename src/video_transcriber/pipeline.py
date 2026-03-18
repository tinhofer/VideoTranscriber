"""Multi-language transcription pipeline for EP webstreaming.

Downloads original floor audio and (if needed) the German interpreter track,
transcribes both, and merges the results: EN/DE segments from the original,
other languages replaced by the German interpretation.
"""

import sys

from video_transcriber.downloader import download_audio
from video_transcriber.postprocess import clean_segments
from video_transcriber.transcriber import detect_segment_languages, transcribe_audio

# Languages to keep from the original floor audio (ISO 639-1 codes).
KEEP_ORIGINAL_LANGUAGES = {"en", "de"}

# The interpreter track to download for non-EN/DE speeches.
INTERPRETER_TRACK = "de"


def _find_closest_segment(target_start, target_end, candidates, tolerance=2.0):
    """Find the candidate segment that best overlaps with the target time range.

    Args:
        target_start: Start time in seconds.
        target_end: End time in seconds.
        candidates: List of segment dicts with 'start' and 'end' keys.
        tolerance: Maximum gap (seconds) to still consider a match.

    Returns:
        The best matching candidate segment, or None.
    """
    best = None
    best_overlap = -1
    for seg in candidates:
        # Calculate overlap
        overlap_start = max(target_start, seg["start"])
        overlap_end = min(target_end, seg["end"])
        overlap = max(0, overlap_end - overlap_start)
        if overlap > best_overlap:
            best_overlap = overlap
            best = seg
    if best_overlap > 0 or (best and abs(best["start"] - target_start) <= tolerance):
        return best
    return None


def _collect_interpreter_segments(interp_segments, start, end):
    """Collect all interpreter segments that fall within a time range.

    Returns a list of interpreter segments overlapping [start, end].
    """
    result = []
    for seg in interp_segments:
        # Segment overlaps if it doesn't end before our start or start after our end
        if seg["end"] > start and seg["start"] < end:
            result.append(seg)
    return result


def run_pipeline(
    url,
    model_size="base",
    output_dir=None,
    keep_original_langs=None,
    interpreter_track=None,
):
    """Run the multi-language transcription pipeline.

    1. Download and transcribe the original floor audio.
    2. Detect language per segment.
    3. If non-EN/DE segments are found, download the German interpreter track,
       transcribe it, and replace those segments.
    4. Apply post-processing (filler removal, repetition cleanup).

    Args:
        url: EP webstreaming URL.
        model_size: Whisper model size.
        output_dir: Directory for audio files. None = temp dir.
        keep_original_langs: Set of language codes to keep from original.
                             Defaults to {'en', 'de'}.
        interpreter_track: Language code for the interpreter audio track.
                           Defaults to 'de'.

    Returns:
        List of cleaned segment dicts with keys: start, end, text, language, source.
    """
    if keep_original_langs is None:
        keep_original_langs = KEEP_ORIGINAL_LANGUAGES
    if interpreter_track is None:
        interpreter_track = INTERPRETER_TRACK

    # Step 1: Download and transcribe original floor audio
    print("Step 1/4: Downloading original floor audio...", file=sys.stderr)
    original_audio = download_audio(url, output_dir=output_dir, audio_track="or")
    print(f"Original audio: {original_audio}", file=sys.stderr)

    print("Step 2/4: Transcribing original audio...", file=sys.stderr)
    original_segments = transcribe_audio(original_audio, model_size=model_size, language=None)

    # Step 2: Detect language per segment
    print("Step 3/4: Detecting languages per segment...", file=sys.stderr)
    original_segments = detect_segment_languages(original_segments)

    # Check if we have segments in non-kept languages
    other_lang_segments = [
        seg
        for seg in original_segments
        if seg.get("language", "unknown") not in keep_original_langs
    ]

    if not other_lang_segments:
        print(
            "All segments are in EN/DE. No interpreter track needed.",
            file=sys.stderr,
        )
        for seg in original_segments:
            seg["source"] = "original"
        return clean_segments(original_segments)

    # Step 3: Download and transcribe interpreter track
    other_count = len(other_lang_segments)
    total_count = len(original_segments)
    print(
        f"Found {other_count}/{total_count} segments in other languages. "
        f"Downloading {interpreter_track.upper()} interpreter track...",
        file=sys.stderr,
    )

    interp_audio = download_audio(url, output_dir=output_dir, audio_track=interpreter_track)
    print(f"Interpreter audio: {interp_audio}", file=sys.stderr)

    print("Step 4/4: Transcribing interpreter track...", file=sys.stderr)
    interp_segments = transcribe_audio(
        interp_audio, model_size=model_size, language=interpreter_track
    )

    # Step 4: Merge — keep EN/DE from original, replace others with interpreter
    merged = []
    for seg in original_segments:
        lang = seg.get("language", "unknown")
        if lang in keep_original_langs:
            seg["source"] = "original"
            merged.append(seg)
        else:
            # Find corresponding interpreter segments for this time range
            interp_matches = _collect_interpreter_segments(
                interp_segments, seg["start"], seg["end"]
            )
            if interp_matches:
                for interp_seg in interp_matches:
                    merged.append(
                        {
                            "start": interp_seg["start"],
                            "end": interp_seg["end"],
                            "text": interp_seg["text"],
                            "language": interpreter_track,
                            "source": "interpreter",
                        }
                    )
            else:
                # No interpreter match found — keep original with note
                seg["source"] = "original"
                merged.append(seg)

    # Deduplicate interpreter segments (multiple original segments may map to
    # the same interpreter segment)
    seen_starts = set()
    deduped = []
    for seg in merged:
        key = (seg["start"], seg["end"], seg["source"])
        if key not in seen_starts:
            seen_starts.add(key)
            deduped.append(seg)

    # Sort by start time
    deduped.sort(key=lambda s: s["start"])

    return clean_segments(deduped)
