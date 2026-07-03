"""Constants, file locations and persisted user settings.

All mutable files (settings, history, logs, models) live in the per-user
platform directories — an installed app cannot write next to its own code
(Program Files / .app bundles are read-only).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, fields

import keyring
import keyring.errors
import platformdirs

log = logging.getLogger(__name__)

APP_NAME = "Kalbukas"
APP_DISPLAY_NAME = "Kalbukas"

DATA_DIR = platformdirs.user_data_dir(APP_NAME, appauthor=False)
LOG_DIR = platformdirs.user_log_dir(APP_NAME, appauthor=False)
MODEL_DIR = os.path.join(DATA_DIR, "models")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.jsonl")

# earlier versions kept everything next to the source checkout
_LEGACY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# pre-rename ("Local Dictation") per-user locations
_OLD_DATA_DIR = platformdirs.user_data_dir("LocalDictation", appauthor=False)
_OLD_LOG_DIR = platformdirs.user_log_dir("LocalDictation", appauthor=False)
_OLD_KEYRING_SERVICE = "LocalDictation"

# "auto" resolves by hardware: best accuracy on an NVIDIA GPU, a size that
# stays responsive on CPU-only / AMD / Apple Silicon machines otherwise
MODEL_CHOICES = ("large-v3", "medium", "small")
GPU_DEFAULT_MODEL = "large-v3"
CPU_DEFAULT_MODEL = "medium"
MODEL_DOWNLOAD_GB = {"large-v3": 3.1, "medium": 1.5, "small": 0.5}

CLAUDE_MODEL = "claude-opus-4-8"
SAMPLE_RATE = 16_000
HISTORY_LIMIT = 500

RELEASES_API_URL = "https://api.github.com/repos/erve01/Kalbukas/releases/latest"
RELEASES_PAGE_URL = "https://github.com/erve01/Kalbukas/releases"

# steers Whisper toward proper diacritics + punctuation
WHISPER_PROMPTS = {
    "lt": "Sveiki, čia lietuviškas diktavimas su taisyklingais skyrybos ženklais.",
    "en": "Hello, this is an English dictation with correct punctuation.",
}


def migrate_legacy_files() -> None:
    """One-time moves from older locations into the current platform dirs:
    the pre-rename "LocalDictation" dirs and the pre-1.0 script-side files.
    A models folder that can't be moved (e.g. locked by another instance)
    is used in place for this run and retried next start."""
    global MODEL_DIR
    _migrate_renamed_dirs()
    _migrate_keyring_service()
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    for name, new_path in (("settings.json", SETTINGS_FILE),
                           ("history.jsonl", HISTORY_FILE)):
        old_path = os.path.join(_LEGACY_DIR, name)
        if os.path.isfile(old_path) and not os.path.exists(new_path):
            try:
                shutil.move(old_path, new_path)
                log.info("Migrated %s to %s", name, DATA_DIR)
            except OSError as exc:
                log.warning("Could not migrate %s: %s", name, exc)
    old_models = os.path.join(_LEGACY_DIR, "models")
    if os.path.isdir(old_models) and not os.path.isdir(MODEL_DIR):
        try:
            shutil.move(old_models, MODEL_DIR)
            log.info("Migrated models folder to %s", MODEL_DIR)
        except OSError as exc:
            log.warning("Could not migrate models folder (%s) - using it in place.", exc)
            MODEL_DIR = old_models


def _migrate_renamed_dirs() -> None:
    # must run before the new dirs are created so a whole-dir rename works
    for old, new in ((_OLD_DATA_DIR, DATA_DIR), (_OLD_LOG_DIR, LOG_DIR)):
        if not os.path.isdir(old):
            continue
        try:
            if not os.path.exists(new):
                shutil.move(old, new)
            else:  # partial earlier migration: move item by item
                for name in os.listdir(old):
                    target = os.path.join(new, name)
                    if not os.path.exists(target):
                        shutil.move(os.path.join(old, name), target)
                os.rmdir(old)
            log.info("Migrated %s -> %s", old, new)
        except OSError as exc:
            log.warning("Could not migrate %s (%s)", old, exc)


def _migrate_keyring_service() -> None:
    try:
        old_key = keyring.get_password(_OLD_KEYRING_SERVICE, _KEYRING_USER)
        if old_key and not keyring.get_password(_KEYRING_SERVICE, _KEYRING_USER):
            keyring.set_password(_KEYRING_SERVICE, _KEYRING_USER, old_key)
            keyring.delete_password(_OLD_KEYRING_SERVICE, _KEYRING_USER)
            log.info("Migrated the API key credential entry to '%s'.", _KEYRING_SERVICE)
    except keyring.errors.KeyringError:
        log.warning("Credential store unavailable for rename migration",
                    exc_info=True)


# The API key lives in the OS credential store (Windows Credential Manager /
# macOS Keychain), never in a plaintext file.
_KEYRING_SERVICE = APP_NAME
_KEYRING_USER = "anthropic-api-key"


def get_api_key() -> str:
    try:
        return keyring.get_password(_KEYRING_SERVICE, _KEYRING_USER) or ""
    except keyring.errors.KeyringError:
        log.warning("Credential store unavailable", exc_info=True)
        return ""


def set_api_key(value: str) -> bool:
    try:
        if value:
            keyring.set_password(_KEYRING_SERVICE, _KEYRING_USER, value)
        else:
            try:
                keyring.delete_password(_KEYRING_SERVICE, _KEYRING_USER)
            except keyring.errors.PasswordDeleteError:
                pass
        return True
    except keyring.errors.KeyringError:
        log.warning("Credential store unavailable", exc_info=True)
        return False


# values a hand-edited settings.json may only take; anything else resets to default
_CHOICES = {
    "language": ("lt", "en"),
    "output": ("paste", "clipboard"),
    "mode": ("offline", "online"),
    "translate": ("off", "lt-en", "en-lt"),
    "model": ("auto",) + MODEL_CHOICES,
}


@dataclass
class Settings:
    """User preferences, persisted to settings.json as they change."""

    language: str = "lt"       # "lt" | "en"
    output: str = "paste"      # "paste" (into the focused app) | "clipboard"
    mode: str = "offline"      # "offline" | "online" (AI cleanup via Claude)
    translate: str = "off"     # "off" | "lt-en" | "en-lt"  (online mode only)
    mic: str = ""              # preferred microphone name ("" = system default)
    hotkey: str = "<f9>"       # pynput format, e.g. "<f9>" or "<ctrl>+<alt>+d"
    save_history: bool = True  # privacy: dictations can be kept out of history
    model: str = "auto"        # "auto" | one of MODEL_CHOICES
    mac_permissions_ack: bool = False  # one-time macOS permissions notice shown

    @classmethod
    def load(cls) -> "Settings":
        defaults = cls()
        data: dict = {}
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as fh:
                raw = json.load(fh)
            # pre-keyring versions kept the API key in this file — move it
            # to the credential store; the save() below scrubs it from disk
            legacy_key = raw.get("api_key")
            if isinstance(legacy_key, str) and legacy_key.strip():
                if set_api_key(legacy_key.strip()):
                    log.info("Migrated API key to the OS credential store.")
            data = {k: v for k, v in raw.items()
                    if hasattr(defaults, k)
                    and isinstance(v, type(getattr(defaults, k)))}
        except (OSError, ValueError):
            pass
        for key, allowed in _CHOICES.items():
            if key in data and data[key] not in allowed:
                del data[key]  # tampered/unknown value -> default
        known = {f.name for f in fields(cls)}
        settings = cls(**{k: v for k, v in data.items() if k in known})
        settings.save()  # ensure the file exists with every key present
        return settings

    def save(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2)
        os.replace(tmp, SETTINGS_FILE)  # atomic: a crash mid-write can't corrupt

    @property
    def effective_api_key(self) -> str:
        return get_api_key() or os.environ.get("ANTHROPIC_API_KEY", "")
