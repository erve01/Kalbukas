"""System tray icon: the app's settings menu."""

from __future__ import annotations

import threading
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from .. import __version__, config, hotkey, updates
from ..audio import list_microphones
from .history_window import HistoryWindow
from .shortcut_dialog import ShortcutDialog

_MODEL_OPTIONS = [("auto", "Auto (recommended)"),
                  ("large-v3", "Large — best accuracy"),
                  ("medium", "Medium — balanced"),
                  ("small", "Small — fastest")]

_SILENCE_OPTIONS = [(seconds, "After %d s" % seconds if seconds else "Off")
                    for seconds in config.SILENCE_TIMEOUT_CHOICES]

_CONFIDENCE_OPTIONS = [("off", "Never"),
                       ("low", "Only when very unsure"),
                       ("medium", "When unsure (recommended)"),
                       ("high", "Unless very sure")]


def _make_icon() -> QtGui.QIcon:
    pixmap = QtGui.QPixmap(64, 64)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    grad = QtGui.QLinearGradient(8, 0, 56, 0)
    grad.setColorAt(0.0, QtGui.QColor(64, 224, 208))
    grad.setColorAt(1.0, QtGui.QColor(192, 132, 255))
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(grad)
    for i, height in enumerate((18, 34, 48, 34, 18)):  # mini waveform glyph
        painter.drawRoundedRect(
            QtCore.QRectF(8 + i * 10.5, 32 - height / 2, 7, height), 3.5, 3.5)
    painter.end()
    return QtGui.QIcon(pixmap)


class Tray(QtCore.QObject):
    _update_result = QtCore.Signal(str, str)  # update-check thread -> balloon

    def __init__(self, app, settings, recorder, history, controller) -> None:
        super().__init__()
        self._app = app
        self._settings = settings
        self._recorder = recorder
        self._history = history
        self._controller = controller
        self._history_window: Optional[HistoryWindow] = None
        self._status: Optional[str] = None       # e.g. "Loading speech model…"
        self._model_ready_once = False
        self._update_url = ""                    # set while an update balloon shows

        app.setWindowIcon(_make_icon())  # history window & dialogs
        self.icon = QtWidgets.QSystemTrayIcon(_make_icon())
        menu = QtWidgets.QMenu()
        self._menu = menu
        self._title = menu.addAction("")
        self._title.setEnabled(False)

        self._group("Language", "language",
                    [("lt", "Lietuvių (LT)"), ("en", "English (EN)")])
        self._group("Output", "output",
                    [("paste", "Auto-paste into app"), ("clipboard", "Clipboard only")])
        self._translate_actions = self._group(
            "Translate", "translate",
            [("off", "Off"), ("lt-en", "LT → EN"), ("en-lt", "EN → LT")])
        self._group("Stop recording on silence", "silence_timeout",
                    _SILENCE_OPTIONS)
        self._group("Ask before using unclear text", "confidence",
                    _CONFIDENCE_OPTIONS)
        self._model_actions = self._group("Model", "model", _MODEL_OPTIONS)

        menu.addSeparator()
        self._mic_menu = menu.addMenu("Microphone")
        # devices come and go (Bluetooth) — rebuild the list on every open
        self._mic_menu.aboutToShow.connect(self._rebuild_mic_menu)
        self._hotkey_action = menu.addAction("")
        self._hotkey_action.triggered.connect(self._change_shortcut)
        self._key_action = menu.addAction("")
        self._key_action.triggered.connect(self._set_api_key)
        menu.addAction("History…").triggered.connect(self._show_history)
        self._save_history_action = menu.addAction("Save history")
        self._save_history_action.setCheckable(True)
        self._save_history_action.setChecked(settings.save_history)
        self._save_history_action.triggered.connect(
            lambda checked: self._set("save_history", checked))

        menu.addSeparator()
        menu.addAction("About…").triggered.connect(self._about)
        if config.RELEASES_API_URL:
            menu.addAction("Check for updates…").triggered.connect(
                self._check_updates)
        menu.addAction("Quit").triggered.connect(self._quit)

        self._update_result.connect(self._show_update_result)
        self.icon.messageClicked.connect(self._on_balloon_clicked)
        self.icon.setContextMenu(menu)
        self._refresh()
        self.icon.show()

    # ---- model / status ---------------------------------------------------
    def set_status(self, text: Optional[str]) -> None:
        self._status = text
        self._refresh()

    def on_model_ready(self) -> None:
        transcriber = self._controller.transcriber
        where = "GPU" if transcriber.device == "cuda" else "CPU"
        if self._model_ready_once:  # hot swap — confirm; initial load stays quiet
            self.icon.showMessage(
                "Model ready", "Now using '%s' on the %s."
                % (transcriber.model_size, where),
                QtWidgets.QSystemTrayIcon.Information, 3000)
        self._model_ready_once = True
        self.set_status(None)

    # ---- menu construction ----------------------------------------------
    def _group(self, header: str, key: str, options) -> list[QtGui.QAction]:
        self._menu.addSeparator()
        header_action = self._menu.addAction(header)
        header_action.setEnabled(False)
        group = QtGui.QActionGroup(self._menu)
        group.setExclusive(True)
        actions = []
        for value, label in options:
            action = self._menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(getattr(self._settings, key) == value)
            action.triggered.connect(lambda _checked, k=key, v=value: self._set(k, v))
            group.addAction(action)
            actions.append(action)
        return actions

    def _rebuild_mic_menu(self) -> None:
        self._mic_menu.clear()
        self._recorder.rescan()  # surface a mic enabled after a mic-less start
        mics = list_microphones()
        if not mics:
            hint = self._mic_menu.addAction("(no microphones found)")
            hint.setEnabled(False)
        group = QtGui.QActionGroup(self._mic_menu)
        group.setExclusive(True)
        entries = [("", "System default")] + [(name, name) for _idx, name in mics]
        for value, label in entries:
            action = self._mic_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self._settings.mic == value)
            action.triggered.connect(lambda _checked, v=value: self._set_mic(v))
            group.addAction(action)

    # ---- handlers ---------------------------------------------------------
    def _set(self, key: str, value: str | int | bool) -> None:
        if key == "model":
            self._set_model(value)
            return
        setattr(self._settings, key, value)
        self._settings.save()
        self._refresh()

    def _set_model(self, value: str) -> None:
        previous = self._settings.model
        self._settings.model = value
        self._settings.save()
        if self._controller.change_model(value):
            if self._controller.loading:
                self.set_status("Loading speech model…")
        else:
            self._settings.model = previous  # download declined / loader busy
            self._settings.save()
            for action, (option, _label) in zip(self._model_actions, _MODEL_OPTIONS):
                action.setChecked(option == previous)
        self._refresh()

    def _set_mic(self, name: str) -> None:
        error = self._recorder.switch(name)
        if error:
            self.icon.showMessage("Microphone", error,
                                  QtWidgets.QSystemTrayIcon.Warning, 4000)
            return
        self._settings.mic = name
        self._settings.save()

    def _change_shortcut(self) -> None:
        self._controller.hotkeys.stop()  # current hotkey must not fire mid-capture
        dialog = ShortcutDialog()
        if dialog.exec() == QtWidgets.QDialog.Accepted and dialog.hotkey:
            self._controller.set_hotkey(dialog.hotkey)
        else:
            self._controller.hotkeys.set_hotkey(self._settings.hotkey)  # restore
        self._refresh()

    def _set_api_key(self) -> None:
        current = self._settings.effective_api_key
        hint = ("current key ends in ...%s" % current[-4:]) if current else "no key set"
        text, ok = QtWidgets.QInputDialog.getText(
            None, "Anthropic API key",
            "Paste your Anthropic API key (%s).\n"
            "Leave empty to keep the current one:" % hint,
            QtWidgets.QLineEdit.Normal, "",
            QtCore.Qt.WindowStaysOnTopHint)
        if ok and text.strip():
            if config.set_api_key(text.strip()):
                message = "Saved to the system credential store."
            else:
                message = ("Could not reach the system credential store — "
                           "the key was not saved.")
            self._refresh()
            self.icon.showMessage("API key", message,
                                  QtWidgets.QSystemTrayIcon.Information, 3000)

    def _show_history(self) -> None:
        if self._history_window is None:
            self._history_window = HistoryWindow(self._history)
        self._history_window.refresh()
        self._history_window.show()
        self._history_window.raise_()
        self._history_window.activateWindow()

    def _about(self) -> None:
        transcriber = self._controller.transcriber
        model_line = ("Speech model: %s (%s)"
                      % (transcriber.model_size,
                         "GPU" if transcriber.device == "cuda" else "CPU")
                      if transcriber else "Speech model: loading…")
        QtWidgets.QMessageBox.about(
            None, "About %s" % config.APP_DISPLAY_NAME,
            "%s %s\n\n%s\n\nSettings & history:\n%s\n\nLogs:\n%s"
            % (config.APP_DISPLAY_NAME, __version__, model_line,
               config.DATA_DIR, config.LOG_DIR))

    # ---- update check -------------------------------------------------------
    def _check_updates(self) -> None:
        threading.Thread(target=self._check_updates_bg, daemon=True).start()

    def _check_updates_bg(self) -> None:
        try:
            newer = updates.check()
        except Exception:
            self._update_result.emit(
                "Update check failed", "The releases page could not be reached.")
            return
        if newer:
            self._update_url = config.RELEASES_PAGE_URL
            self._update_result.emit(
                "Update available",
                "Version %s is out — click here to open the download page." % newer)
        else:
            self._update_result.emit("Up to date",
                                     "You have the newest version (%s)." % __version__)

    def _show_update_result(self, title: str, message: str) -> None:
        self.icon.showMessage(title, message,
                              QtWidgets.QSystemTrayIcon.Information, 6000)

    def _on_balloon_clicked(self) -> None:
        if self._update_url:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(self._update_url))
            self._update_url = ""

    # ---- shared -------------------------------------------------------------
    def _refresh(self) -> None:
        shortcut = hotkey.display(self._settings.hotkey)
        has_key = bool(self._settings.effective_api_key)
        self._title.setText(self._status or "%s — press %s"
                            % (config.APP_DISPLAY_NAME, shortcut))
        self._hotkey_action.setText("Change shortcut…  (%s)" % shortcut)
        self._key_action.setText(
            "Set API key…  (%s)" % ("set ✓" if has_key else "not set"))
        for action in self._translate_actions:  # translation runs via Claude
            action.setEnabled(has_key)
        cleanup = "AI cleanup" if has_key else "local only"
        translate = (", translate " + self._settings.translate
                     if has_key and self._settings.translate != "off" else "")
        status = " — " + self._status if self._status else ""
        self.icon.setToolTip("%s (%s) — %s, %s%s%s" % (
            config.APP_DISPLAY_NAME, shortcut, self._settings.language.upper(),
            cleanup, translate, status))

    def _quit(self) -> None:
        self._controller.shutdown()
        self._app.quit()
