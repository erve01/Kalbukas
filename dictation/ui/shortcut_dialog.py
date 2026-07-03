"""Press-to-set capture dialog for the dictation shortcut."""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets
from pynput import keyboard

from ..hotkey import combo_string, is_modifier, key_token


class ShortcutDialog(QtWidgets.QDialog):
    """Captures the next key/combo pressed. On accept, ``hotkey`` holds the
    pynput-format string (e.g. "<f9>", "<ctrl>+<alt>+d")."""

    _captured = QtCore.Signal(str)  # pynput thread -> Qt thread

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Change shortcut")
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
        self.setFixedSize(320, 110)
        self.hotkey: str | None = None
        self._held: set[str] = set()

        layout = QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel("Press the new dictation shortcut\n"
                                 "(e.g. F9 or Ctrl+Alt+D) — Esc cancels")
        label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(label)

        self._captured.connect(self._finish)
        self._listener = keyboard.Listener(on_press=self._on_press,
                                           on_release=self._on_release)
        self._listener.start()

    # pynput listener thread — only emit signals, never touch Qt directly
    def _on_press(self, key) -> None:
        if key == keyboard.Key.esc:
            self._captured.emit("")
            return
        token = key_token(key)
        if token is None:
            return
        if is_modifier(token):
            self._held.add(token)
        else:
            self._captured.emit(combo_string(self._held, token))

    def _on_release(self, key) -> None:
        token = key_token(key)
        if token and is_modifier(token):
            self._held.discard(token)

    def _finish(self, hotkey: str) -> None:
        self.hotkey = hotkey or None
        if hotkey:
            self.accept()
        else:
            self.reject()

    def done(self, result: int) -> None:
        self._listener.stop()
        super().done(result)
