"""Update check against the project's GitHub releases feed."""

from __future__ import annotations

import json
import urllib.request
from typing import Optional

from . import __version__
from .config import RELEASES_API_URL


def _as_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.strip().lstrip("v").split("."))


def check() -> Optional[str]:
    """Newest released version if it is newer than this build, else None.
    Raises on network/parse errors — the caller owns user feedback."""
    with urllib.request.urlopen(RELEASES_API_URL, timeout=10) as response:
        latest = json.load(response)["tag_name"]
    if _as_tuple(latest) > _as_tuple(__version__):
        return latest.lstrip("v")
    return None
