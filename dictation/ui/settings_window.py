"""Settings window — every preference in one place, applied as you change it.

Replaces the old tray context menu so several settings can be changed without
reopening the menu each time. Each control writes straight through to the
Settings object and triggers the same side effect the old menu handlers did
(model hot-swap, mic switch, network lock).
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6 import QtCore, QtWidgets

from .. import config, hotkey, netlock
from ..audio import list_microphones
from .history_window import HistoryWindow
from .shortcut_dialog import ShortcutDialog

# (settings key, row label, [(value, item text), ...]) for the plain dropdowns
_CHOICE_FIELDS = [
    ("language", "Language",
     [("lt", "Lietuvių (LT)"), ("en", "English (EN)")]),
    ("mode", "Mode",
     [("offline", "Offline — nothing leaves your PC"),
      ("online", "Online — AI cleanup via Claude")]),
    ("output", "Output",
     [("paste", "Auto-paste into the app"), ("clipboard", "Copy to clipboard")]),
    ("translate", "Translate",
     [("off", "Off"), ("lt-en", "LT → EN"), ("en-lt", "EN → LT")]),
    ("silence_timeout", "Stop on silence",
     [(s, "Off" if not s else "After %d s" % s)
      for s in config.SILENCE_TIMEOUT_CHOICES]),
    ("confidence", "Ask before unclear text",
     [("off", "Never"), ("low", "Only when very unsure"),
      ("medium", "When unsure (recommended)"), ("high", "Unless very sure")]),
    ("model", "Speech model",
     [("auto", "Auto (recommended)"), ("large-v3", "Large — best accuracy"),
      ("medium", "Medium — balanced"), ("small", "Small — fastest")]),
]


class SettingsWindow(QtWidgets.QDialog):
    """Non-modal settings form. Stays open; every change saves immediately."""

    def __init__(self, settings, recorder, history, controller,
                 set_status: Callable[[Optional[str]], None]) -> None:
        super().__init__()
        self._settings = settings
        self._recorder = recorder
        self._history = history
        self._controller = controller
        self._set_status = set_status
        self._history_window: Optional[HistoryWindow] = None

        self.setWindowTitle("%s — Settings" % config.APP_DISPLAY_NAME)
        self.setMinimumWidth(460)
        form = QtWidgets.QFormLayout(self)
        form.setLabelAlignment(QtCore.Qt.AlignRight)

        note = QtWidgets.QLabel("Changes apply and save as you make them.")
        note.setStyleSheet("color: gray;")
        form.addRow(note)

        self._combos: dict[str, QtWidgets.QComboBox] = {}
        for key, label, options in _CHOICE_FIELDS:
            combo = QtWidgets.QComboBox()
            for value, text in options:
                combo.addItem(text, value)
            self._select(combo, getattr(settings, key))
            combo.currentIndexChanged.connect(
                lambda _i, k=key: self._on_choice(k))
            self._combos[key] = combo
            form.addRow(label + ":", combo)

        self._mic_combo = QtWidgets.QComboBox()
        self._mic_combo.activated.connect(self._on_mic)
        form.addRow("Microphone:", self._mic_combo)

        self._save_history = QtWidgets.QCheckBox("Keep a history of dictations")
        self._save_history.setChecked(settings.save_history)
        self._save_history.toggled.connect(self._on_save_history)
        form.addRow("History:", self._save_history)

        self._shortcut_btn = QtWidgets.QPushButton()
        self._shortcut_btn.clicked.connect(self._change_shortcut)
        form.addRow("Shortcut:", self._shortcut_btn)

        self._key_btn = QtWidgets.QPushButton()
        self._key_btn.clicked.connect(self._set_api_key)
        form.addRow("Anthropic API key:", self._key_btn)

        buttons = QtWidgets.QHBoxLayout()
        history_btn = QtWidgets.QPushButton("Open history…")
        history_btn.clicked.connect(self._show_history)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.hide)
        buttons.addWidget(history_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        form.addRow(buttons)

        self._refresh_controls()

    # ---- public -----------------------------------------------------------
    def refresh(self) -> None:
        """Re-read dynamic state each time the window is opened."""
        self._rebuild_mics()
        self._refresh_controls()

    # ---- helpers ----------------------------------------------------------
    @staticmethod
    def _select(combo: QtWidgets.QComboBox, value) -> None:
        combo.blockSignals(True)
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _rebuild_mics(self) -> None:
        self._recorder.rescan()  # surface a mic connected after startup
        self._mic_combo.blockSignals(True)
        self._mic_combo.clear()
        self._mic_combo.addItem("System default", "")
        for _index, name in list_microphones():
            self._mic_combo.addItem(name, name)
        index = self._mic_combo.findData(self._settings.mic)
        self._mic_combo.setCurrentIndex(index if index >= 0 else 0)
        self._mic_combo.blockSignals(False)

    def _refresh_controls(self) -> None:
        online = self._settings.mode == "online"
        has_key = bool(self._settings.effective_api_key)
        self._combos["translate"].setEnabled(online and has_key)  # needs Claude
        self._shortcut_btn.setText(
            "Change…  (%s)" % hotkey.display(self._settings.hotkey))
        self._key_btn.setText("Set ✓ — click to replace" if has_key
                              else "Not set — click to add")

    # ---- handlers ---------------------------------------------------------
    def _on_choice(self, key: str) -> None:
        value = self._combos[key].currentData()
        if key == "model":
            self._on_model(value)
            return
        setattr(self._settings, key, value)
        self._settings.save()
        if key == "mode":
            netlock.apply(value)  # block/unblock the network to match the mode
        self._refresh_controls()

    def _on_model(self, value: str) -> None:
        previous = self._settings.model
        if value == previous:
            return
        self._settings.model = value
        self._settings.save()
        if self._controller.change_model(value):
            if self._controller.loading:
                self._set_status("Loading speech model…")
        else:  # download declined / loader busy — revert the dropdown
            self._settings.model = previous
            self._settings.save()
            self._select(self._combos["model"], previous)

    def _on_mic(self, _index: int) -> None:
        name = self._mic_combo.currentData()
        error = self._recorder.switch(name)
        if error:
            QtWidgets.QMessageBox.warning(self, "Microphone", error)
            self._rebuild_mics()  # revert to what actually opened
            return
        self._settings.mic = name
        self._settings.save()

    def _on_save_history(self, checked: bool) -> None:
        self._settings.save_history = checked
        self._settings.save()

    def _change_shortcut(self) -> None:
        self._controller.hotkeys.stop()  # current hotkey must not fire mid-capture
        dialog = ShortcutDialog()
        if dialog.exec() == QtWidgets.QDialog.Accepted and dialog.hotkey:
            self._controller.set_hotkey(dialog.hotkey)
        else:
            self._controller.hotkeys.set_hotkey(self._settings.hotkey)  # restore
        self._refresh_controls()

    def _set_api_key(self) -> None:
        current = self._settings.effective_api_key
        hint = ("current key ends in ...%s" % current[-4:]) if current else "no key set"
        text, ok = QtWidgets.QInputDialog.getText(
            self, "Anthropic API key",
            "Paste your Anthropic API key (%s).\n"
            "Leave empty to keep the current one:" % hint,
            QtWidgets.QLineEdit.Normal, "")
        if ok and text.strip():
            config.set_api_key(text.strip())
        self._refresh_controls()

    def _show_history(self) -> None:
        if self._history_window is None:
            self._history_window = HistoryWindow(self._history)
        self._history_window.refresh()
        self._history_window.show()
        self._history_window.raise_()
        self._history_window.activateWindow()
