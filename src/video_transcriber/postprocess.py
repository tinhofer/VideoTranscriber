"""Post-processing for transcription segments: filler removal, repetition cleanup."""

import re

# Filler words/phrases to remove, grouped by language.
# Each pattern is compiled as a regex matching the filler as a whole word.
FILLERS_DE = [
    r"\bähm\b",
    r"\bäh\b",
    r"\bah\b",
    r"\bhm+\b",
    r"\bmhm\b",
    r"\bnaja\b",
    r"\bsozusagen\b",
    r"\bquasi\b",
    r"\bsagen wir mal\b",
    r"\bich meine\b",
    r"\bja also\b",
]

FILLERS_EN = [
    r"\bum\b",
    r"\buh\b",
    r"\bah\b",
    r"\bhm+\b",
    r"\bmhm\b",
    r"\byou know\b",
    r"\bI mean\b",
    r"\blike\b(?=\s*,)",  # "like" only when followed by comma (filler usage)
    r"\bso\b(?=\s*,)",  # "so" only when followed by comma (filler usage)
    r"\bbasically\b(?=\s*,)",
    r"\bactually\b(?=\s*,)",
]

# Compiled patterns (case-insensitive)
_FILLER_PATTERNS = [re.compile(p, re.IGNORECASE) for p in FILLERS_DE + FILLERS_EN]

# Pattern for consecutive duplicate phrases (2+ words repeated immediately)
_REPETITION_PATTERN = re.compile(
    r"\b((?:\w+\s+){1,5}?\w+)\s+\1\b",
    re.IGNORECASE,
)

# Cleanup: multiple spaces, space before punctuation
_MULTI_SPACE = re.compile(r"  +")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.\?!;:])")


def remove_fillers(text):
    """Remove filler words from text."""
    for pattern in _FILLER_PATTERNS:
        text = pattern.sub("", text)
    # Remove leftover orphan commas: ", ," or leading commas
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"^\s*,\s*", "", text)
    text = _MULTI_SPACE.sub(" ", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    return text.strip()


def remove_repetitions(text):
    """Remove consecutive duplicate phrases (e.g. 'we must we must act' → 'we must act')."""
    # Apply multiple times since removal may reveal new repetitions
    for _ in range(3):
        new_text = _REPETITION_PATTERN.sub(r"\1", text)
        if new_text == text:
            break
        text = new_text
    return text


def clean_segments(segments):
    """Apply filler removal and repetition cleanup to all segments.

    Args:
        segments: List of segment dicts with 'text' key.

    Returns:
        List of segments with cleaned text. Empty segments are removed.
    """
    cleaned = []
    for seg in segments:
        text = seg["text"]
        text = remove_fillers(text)
        text = remove_repetitions(text)
        text = text.strip()
        if text:
            cleaned.append({**seg, "text": text})
    return cleaned
