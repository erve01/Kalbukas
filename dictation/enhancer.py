"""Claude post-processing for online mode: fix dictation errors, translate."""

from __future__ import annotations

import logging
from typing import Optional

try:
    import anthropic
except ImportError:
    anthropic = None

from .config import CLAUDE_MODEL, Settings

log = logging.getLogger(__name__)

_LANGUAGE_NAMES = {"lt": "Lithuanian", "en": "English"}


def enhance(text: str, settings: Settings) -> Optional[str]:
    """Return polished (and optionally translated) text, or None so the
    caller falls back to the raw transcription — a network/API failure must
    never lose a dictation."""
    api_key = settings.effective_api_key
    if anthropic is None or not api_key:
        log.info("(online mode: no anthropic SDK or API key - skipping AI cleanup)")
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=30.0, max_retries=1)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8192,
            output_config={"effort": "low"},  # latency-sensitive cleanup, not deep reasoning
            system=_system_prompt(settings),
            messages=[{"role": "user", "content": text}],
        )
        if response.stop_reason == "refusal" or not response.content:
            return None
        polished = "".join(block.text for block in response.content
                           if block.type == "text").strip()
        return polished or None
    except Exception as exc:
        log.info("AI cleanup failed (%s) - using raw transcription.", exc)
        return None


def _system_prompt(settings: Settings) -> str:
    prompt = (
        "You clean up dictated speech-to-text output in %s. "
        "Fix transcription errors, grammar, punctuation, capitalization and "
        "diacritics. Keep the speaker's meaning, wording and tone - do not "
        "rewrite or embellish." % _LANGUAGE_NAMES[settings.language]
    )
    if settings.translate == "lt-en":
        prompt += (" Then translate the corrected text from Lithuanian to English."
                   " Reply with ONLY the English translation - no original text,"
                   " no quotes, no commentary.")
    elif settings.translate == "en-lt":
        prompt += (" Then translate the corrected text from English to Lithuanian."
                   " Reply with ONLY the Lithuanian translation - no original text,"
                   " no quotes, no commentary.")
    else:
        prompt += " Reply with ONLY the final text - no quotes, no commentary."
    return prompt
