"""System tray icon: live status, quick actions, and the Settings launcher."""

from __future__ import annotations

import threading
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from .. import __version__, config, hotkey, updates
from .history_window import HistoryWindow
from .settings_window import SettingsWindow


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
        self._settings_window: Optional[SettingsWindow] = None
        self._history_window: Optional[HistoryWindow] = None
        self._status: Optional[str] = None       # e.g. "Loading speech model…"
        self._model_ready_once = False
        self._update_url = ""                    # set while an update balloon shows

        app.setWindowIcon(_make_icon())  # settings/history windows & dialogs
        self.icon = QtWidgets.QSystemTrayIcon(_make_icon())
        menu = QtWidgets.QMenu()
        self._title = menu.addAction("")
        self._title.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Settings…").triggered.connect(self._show_settings)
        menu.addAction("History…").triggered.connect(self._show_history)
        menu.addSeparator()
        menu.addAction("About…").triggered.connect(self._about)
        if config.RELEASES_API_URL:
            menu.addAction("Check for updates…").triggered.connect(
                self._check_updates)
        menu.addAction("Quit").triggered.connect(self._quit)

        self.icon.activated.connect(self._on_icon_activated)  # double-click => Settings
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

    # ---- windows ----------------------------------------------------------
    def _show_settings(self) -> None:
        if self._settings_window is None:
            self._settings_window = SettingsWindow(
                self._settings, self._recorder, self._history,
                self._controller, self.set_status)
        self._settings_window.refresh()
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def _show_history(self) -> None:
        if self._history_window is None:
            self._history_window = HistoryWindow(self._history)
        self._history_window.refresh()
        self._history_window.show()
        self._history_window.raise_()
        self._history_window.activateWindow()

    def _on_icon_activated(self, reason) -> None:
        if reason == QtWidgets.QSystemTrayIcon.DoubleClick:
            self._show_settings()

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
        if self._settings.mode == "offline":
            self.icon.showMessage(
                "Offline mode", "Switch to Online to check for updates — "
                "offline mode blocks all network use.",
                QtWidgets.QSystemTrayIcon.Information, 4000)
            return
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
        online = self._settings.mode == "online"
        self._title.setText(self._status or "%s — press %s"
                            % (config.APP_DISPLAY_NAME, shortcut))
        cleanup = "AI cleanup" if (has_key and online) else "local only"
        status = " — " + self._status if self._status else ""
        self.icon.setToolTip("%s (%s) — %s, %s%s" % (
            config.APP_DISPLAY_NAME, shortcut, self._settings.language.upper(),
            cleanup, status))

    def _quit(self) -> None:
        self._controller.shutdown()
        self._app.quit()
