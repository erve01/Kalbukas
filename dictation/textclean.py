"""Deterministic transcript cleanup applied before any AI polishing.

Only unambiguous fixes live here — non-lexical filler sounds, obvious ASR
stutter loops, punctuation debris the removals leave behind. Anything that
needs judgement (real-word fillers, self-corrections, misheard words) is
left to the Claude pass, which sees the surrounding context.
"""

from __future__ import annotations

import re

# Non-lexical hesitation sounds only. Real words that double as fillers
# ("like", "nu", "žinai") stay — stripping those can change the meaning.
_FILLERS = {
    "en": ("uh", "uhh", "um", "umm", "uhm", "erm", "hmm", "mhm", "mm"),
    "lt": ("em", "emm", "ee", "eee", "ėė", "ėėė", "mm", "mmm", "khm"),
}

# Whisper hallucinates these on silence/noise (YouTube-caption training data).
# Exact matches only — anything a user could plausibly dictate stays out.
_HALLUCINATIONS = {
    "en": ("thanks for watching", "thank you for watching", "you"),
    "lt": ("ačiū, kad žiūrėjote",),
}
_CAPTION_CREDITS = ("subtitles by", "subtitrai")  # nobody dictates credits


def clean(text: str, language: str) -> str:
    """Filler sounds out, 3+ word stutters collapsed, punctuation tidied.
    Returns "" when nothing meaningful is left (e.g. pure hallucination)."""
    if not text:
        return ""
    result = text
    fillers = "|".join(_FILLERS.get(language, ()))
    if fillers:
        # the filler plus whatever punctuation Whisper attached to it
        result = re.sub(r"(?i)(?<![\wÀ-ſ])(?:%s)(?![\wÀ-ſ])[,.!?]?" % fillers,
                        "", result)
    # 3+ identical consecutive words are ASR stutter, not emphasis
    # ("labai labai" is legit Lithuanian — only collapse from the third copy)
    result = re.sub(r"(?i)\b([\wÀ-ſ']+)(?:[,\s]+\1\b){2,}", r"\1", result)
    result = _tidy_punctuation(result)
    if _is_hallucination(result, language):
        return ""
    # a removed leading filler ("Um, hello…") takes the capital with it
    if text[:1].isupper() and result[:1].islower():
        result = result[0].upper() + result[1:]
    return result


def _tidy_punctuation(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)      # "word ," -> "word,"
    text = re.sub(r"([,.!?;:])(?:\s*[,.!?;:])+", r"\1", text)  # ",." -> ","
    text = re.sub(r"^[\s,.;:!?]+", "", text)          # debris where a filler led
    return text.strip()


def _is_hallucination(text: str, language: str) -> bool:
    """True when the whole transcript is a known silence artifact."""
    lowered = text.lower().strip(" .,!?")
    if lowered in _HALLUCINATIONS.get(language, ()):
        return True
    return any(lowered.startswith(prefix) for prefix in _CAPTION_CREDITS)
