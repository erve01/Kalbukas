"""Low-confidence transcript review: confirm, fix or discard before use."""

from __future__ import annotations

from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from ..config import APP_DISPLAY_NAME


class ReviewDialog(QtWidgets.QDialog):
    """Shown when Whisper wasn't sure it heard right. The user edits the
    text in place; only the confirmed version continues to AI cleanup and
    pasting, so a bad transcription never reaches Claude or the target app."""

    def __init__(self, text: str, confidence: float) -> None:
        super().__init__(None, QtCore.Qt.WindowStaysOnTopHint)
        self.setWindowTitle(APP_DISPLAY_NAME)
        self.setMinimumWidth(460)

        layout = QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel(
            "This didn't come through clearly (%d%% confidence).\n"
            "Check the text, fix it if needed, then use it — or discard "
            "the take." % round(confidence * 100))
        layout.addWidget(label)

        self._editor = QtWidgets.QPlainTextEdit(text)
        self._editor.setTabChangesFocus(True)
        layout.addWidget(self._editor)

        buttons = QtWidgets.QDialogButtonBox()
        use_btn = buttons.addButton("Use text", QtWidgets.QDialogButtonBox.AcceptRole)
        buttons.addButton("Discard", QtWidgets.QDialogButtonBox.RejectRole)
        use_btn.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._editor.setFocus()
        cursor = self._editor.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self._editor.setTextCursor(cursor)

    @staticmethod
    def get_text(text: str, confidence: float) -> Optional[str]:
        """Run the dialog; the confirmed (possibly edited) text, or None
        when the user discarded the take or emptied the text."""
        dialog = ReviewDialog(text, confidence)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return None
        return dialog._editor.toPlainText().strip() or None
