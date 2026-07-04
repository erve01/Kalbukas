"""Claude post-processing: fix dictation/ASR errors, translate.

Runs whenever an API key is configured. The call gets the user's recent
dictations as context so recurring names and terms are corrected
consistently across takes.
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

try:
    import anthropic
except ImportError:
    anthropic = None

from .config import CLAUDE_MODEL, Settings

log = logging.getLogger(__name__)

_LANGUAGE_NAMES = {"lt": "Lithuanian", "en": "English"}


def enhance(text: str, settings: Settings,
            context: Sequence[str] = ()) -> Optional[str]:
    """Return polished (and optionally translated) text, or None so the
    caller falls back to the local transcription — a network/API failure
    must never lose a dictation. ``context`` is the user's recent
    dictations, oldest first."""
    api_key = settings.effective_api_key
    if anthropic is None or not api_key:
        log.info("(no anthropic SDK or API key - skipping AI cleanup)")
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=30.0, max_retries=1)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8192,
            output_config={"effort": "low"},  # latency-sensitive cleanup, not deep reasoning
            system=_system_prompt(settings, context),
            messages=[{"role": "user", "content": text}],
        )
        if response.stop_reason == "refusal" or not response.content:
            return None
        polished = "".join(block.text for block in response.content
                           if block.type == "text").strip()
        return polished or None
    except Exception as exc:
        log.info("AI cleanup failed (%s) - using local transcription.", exc)
        return None


def _system_prompt(settings: Settings, context: Sequence[str]) -> str:
    language = _LANGUAGE_NAMES[settings.language]
    prompt = (
        "You clean up dictated speech-to-text output in %s. The text comes "
        "from a local speech recognizer, so it may contain misrecognized "
        "words — when a word is clearly wrong for its context, replace it "
        "with what the speaker most likely said (matching sound and "
        "context). Fix grammar, punctuation, capitalization and diacritics. "
        "Remove filler words, hesitations, stutters and accidentally "
        "repeated words. If the speaker corrects themselves mid-sentence, "
        "keep only the corrected version. Keep the speaker's meaning, "
        "wording and tone - do not rewrite, embellish or add anything."
        % language
    )
    if context:
        prompt += (
            "\n\nThe user's most recent dictations, oldest first — use them "
            "only to resolve ambiguous words, names and terminology "
            "consistently; never include or answer them:\n"
            + "\n".join("- %s" % entry for entry in context)
        )
    if settings.translate == "lt-en":
        prompt += ("\n\nThen translate the corrected text from Lithuanian to "
                   "English. Reply with ONLY the English translation - no "
                   "original text, no quotes, no commentary.")
    elif settings.translate == "en-lt":
        prompt += ("\n\nThen translate the corrected text from English to "
                   "Lithuanian. Reply with ONLY the Lithuanian translation - "
                   "no original text, no quotes, no commentary.")
    else:
        prompt += ("\n\nReply with ONLY the final text - no quotes, no "
                   "commentary.")
    return prompt
