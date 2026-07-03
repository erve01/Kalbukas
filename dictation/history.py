"""Dictation history, persisted as JSON Lines and capped at HISTORY_LIMIT."""

from __future__ import annotations

import json
import os
import time

from .config import DATA_DIR, HISTORY_FILE, HISTORY_LIMIT, Settings


class History:
    def __init__(self) -> None:
        self._entries: list[dict] = self._read()

    def add(self, text: str, raw: str, settings: Settings) -> None:
        self._entries.append({
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "text": text,
            # keep the pre-AI transcription only when it differs
            "raw": raw if raw != text else "",
            "language": settings.language,
            "mode": settings.mode,
            "translate": settings.translate,
        })
        del self._entries[:-HISTORY_LIMIT]
        self._write()

    def entries(self) -> list[dict]:
        """Newest first."""
        return list(reversed(self._entries))

    def _read(self) -> list[dict]:
        entries: list[dict] = []
        try:
            with open(HISTORY_FILE, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except ValueError:
                        continue  # skip a corrupt line rather than lose the file
        except FileNotFoundError:
            pass
        return entries[-HISTORY_LIMIT:]

    def _write(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = HISTORY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            for entry in self._entries:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        os.replace(tmp, HISTORY_FILE)  # atomic: a crash mid-write can't corrupt
