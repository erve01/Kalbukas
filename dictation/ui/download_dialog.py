"""First-run model download with progress — replaces the manual --download step."""

from __future__ import annotations

import logging
import threading

from PySide6 import QtCore, QtWidgets

from .. import netlock, transcriber
from ..config import APP_DISPLAY_NAME, MODEL_DOWNLOAD_GB

log = logging.getLogger(__name__)


class DownloadDialog(QtWidgets.QDialog):
    """Modal one-time model download. Network is only opened after the user
    clicks Download; the caller restores the netlock afterwards. Cancelling
    keeps the partial files — the next attempt resumes where it stopped."""

    _done = QtCore.Signal()
    _failed = QtCore.Signal(str)

    def __init__(self, size: str) -> None:
        super().__init__(None, QtCore.Qt.WindowStaysOnTopHint)
        self._size = size
        self._total = int(MODEL_DOWNLOAD_GB[size] * 1e9)
        self.setWindowTitle(APP_DISPLAY_NAME)
        self.setMinimumWidth(420)

        layout = QtWidgets.QVBoxLayout(self)
        self._label = QtWidgets.QLabel(
            "The '%s' speech model (~%.1f GB) needs a one-time download.\n"
            "After that, transcription runs fully on this computer."
            % (size, MODEL_DOWNLOAD_GB[size]))
        layout.addWidget(self._label)
        self._bar = QtWidgets.QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.hide()
        layout.addWidget(self._bar)

        buttons = QtWidgets.QDialogButtonBox()
        self._download_btn = buttons.addButton(
            "Download", QtWidgets.QDialogButtonBox.AcceptRole)
        self._quit_btn = buttons.addButton(
            "Quit", QtWidgets.QDialogButtonBox.RejectRole)
        self._download_btn.clicked.connect(self._start)
        self._quit_btn.clicked.connect(self.reject)
        layout.addWidget(buttons)

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._done.connect(self._on_done)
        self._failed.connect(self._on_failed)

    def _start(self) -> None:
        self._download_btn.setEnabled(False)
        self._quit_btn.setText("Cancel")
        self._label.setText(
            "Downloading the '%s' model… This can take a few minutes.\n"
            "A cancelled download resumes next time." % self._size)
        self._bar.show()
        netlock.apply("online")  # the one sanctioned network use for models
        threading.Thread(target=self._work, daemon=True).start()
        self._timer.start(500)

    def _work(self) -> None:
        try:
            transcriber.download(self._size)
        except Exception as exc:
            log.exception("Model download failed")
            self._failed.emit(str(exc))
            return
        self._done.emit()

    def _poll(self) -> None:
        done = transcriber.downloaded_bytes(self._size) * 100 // self._total
        self._bar.setValue(min(99, int(done)))  # 100 only on confirmed success

    def _on_done(self) -> None:
        self._timer.stop()
        self._bar.setValue(100)
        self.accept()

    def _on_failed(self, message: str) -> None:
        self._timer.stop()
        self._bar.hide()
        self._label.setText(
            "The download failed:\n%s\n\n"
            "Check your internet connection and try again." % message)
        self._download_btn.setText("Retry")
        self._download_btn.setEnabled(True)
        self._quit_btn.setText("Quit")
