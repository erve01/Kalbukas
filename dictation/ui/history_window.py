"""Dictation history viewer: entry list, full-text preview, copy."""

from __future__ import annotations

import pyperclip
from PySide6 import QtCore, QtWidgets

from ..history import History

_PREVIEW_CHARS = 80


class HistoryWindow(QtWidgets.QWidget):
    def __init__(self, history: History) -> None:
        super().__init__()
        self._history = history
        self._entries: list[dict] = []
        self.setWindowTitle("Dictation history")
        self.resize(560, 420)

        self._list = QtWidgets.QListWidget()
        self._list.currentRowChanged.connect(self._show_entry)
        self._list.itemDoubleClicked.connect(lambda _item: self._copy())
        self._preview = QtWidgets.QPlainTextEdit()
        self._preview.setReadOnly(True)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        splitter.addWidget(self._list)
        splitter.addWidget(self._preview)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        hint = QtWidgets.QLabel("Double-click an entry to copy it.")
        hint.setStyleSheet("color: gray;")
        copy_button = QtWidgets.QPushButton("Copy")
        copy_button.clicked.connect(self._copy)
        button_row = QtWidgets.QHBoxLayout()
        button_row.addWidget(hint)
        button_row.addStretch(1)
        button_row.addWidget(copy_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(splitter)
        layout.addLayout(button_row)

    def refresh(self) -> None:
        self._entries = self._history.entries()  # newest first
        self._list.clear()
        for entry in self._entries:
            one_line = " ".join(entry.get("text", "").split())
            if len(one_line) > _PREVIEW_CHARS:
                one_line = one_line[:_PREVIEW_CHARS - 3] + "…"
            self._list.addItem("%s   %s" % (entry.get("ts", ""), one_line))
        if self._entries:
            self._list.setCurrentRow(0)
        else:
            self._preview.setPlainText("(no dictations yet)")

    def _show_entry(self, row: int) -> None:
        if 0 <= row < len(self._entries):
            entry = self._entries[row]
            detail = entry.get("text", "")
            if entry.get("raw"):
                detail += "\n\n— raw transcription —\n" + entry["raw"]
            self._preview.setPlainText(detail)

    def _copy(self) -> None:
        row = self._list.currentRow()
        if 0 <= row < len(self._entries):
            pyperclip.copy(self._entries[row].get("text", ""))
