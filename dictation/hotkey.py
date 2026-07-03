"""Global dictation hotkey: string format, tokenizing and listening.

Hotkeys are stored in pynput's format ("<f9>", "<ctrl>+<alt>+d") and shown
to the user as "F9" / "Ctrl+Alt+D".
"""

from __future__ import annotations

from typing import Callable, Optional

from pynput import keyboard

_MODIFIER_TOKENS = {
    "ctrl": "<ctrl>", "ctrl_l": "<ctrl>", "ctrl_r": "<ctrl>",
    "alt": "<alt>", "alt_l": "<alt>", "alt_r": "<alt>", "alt_gr": "<alt>",
    "shift": "<shift>", "shift_l": "<shift>", "shift_r": "<shift>",
    "cmd": "<cmd>", "cmd_l": "<cmd>", "cmd_r": "<cmd>",
}
_MODIFIER_ORDER = {"<ctrl>": 0, "<alt>": 1, "<shift>": 2, "<cmd>": 3}


def display(hotkey: str) -> str:
    """'<ctrl>+<alt>+d' -> 'Ctrl+Alt+D'."""
    return "+".join(part.strip("<>").capitalize() for part in hotkey.split("+"))


def key_token(key) -> Optional[str]:
    """Canonical token for a pressed key, or None if it can't be represented."""
    if isinstance(key, keyboard.Key):
        return _MODIFIER_TOKENS.get(key.name, "<%s>" % key.name)
    # KeyCode: prefer the virtual-key code — with Ctrl held, .char degrades
    # to control characters ('\x04' for D) on Windows.
    vk = getattr(key, "vk", None)
    if vk is not None and (0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A):
        return chr(vk).lower()
    char = getattr(key, "char", None)
    if char and char.isprintable():
        return char.lower()
    return None


def is_modifier(token: str) -> bool:
    return token in _MODIFIER_ORDER


def combo_string(held_modifiers: set[str], final_token: str) -> str:
    parts = sorted(held_modifiers, key=_MODIFIER_ORDER.__getitem__)
    return "+".join(parts + [final_token])


class HotkeyListener:
    """Owns the pynput global listener for the dictation hotkey.

    Implemented with a plain Listener and our own token matching instead of
    ``keyboard.GlobalHotKeys`` — that class silently never fires for function
    keys on Windows. Using ``key_token`` for both capture (ShortcutDialog)
    and matching guarantees the two agree on key names.
    """

    def __init__(self, hotkey: str, on_activate: Callable[[], None]) -> None:
        self._on_activate = on_activate
        self._listener: Optional[keyboard.Listener] = None
        self._combo: frozenset[str] = frozenset()
        self._pressed: set[str] = set()
        self.set_hotkey(hotkey)

    def set_hotkey(self, hotkey: str) -> None:
        self.stop()
        self._combo = frozenset(hotkey.split("+"))
        self._pressed = set()
        self._listener = keyboard.Listener(on_press=self._on_press,
                                           on_release=self._on_release)
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def _on_press(self, key) -> None:
        token = key_token(key)
        if token is None or token not in self._combo:
            return
        newly_pressed = token not in self._pressed  # ignore key auto-repeat
        self._pressed.add(token)
        if newly_pressed and self._pressed == self._combo:
            self._on_activate()

    def _on_release(self, key) -> None:
        token = key_token(key)
        if token is not None:
            self._pressed.discard(token)
