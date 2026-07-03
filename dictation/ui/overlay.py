"""Frameless always-on-top glass pill with a reactive gradient waveform."""

from __future__ import annotations

import math

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from ..config import Settings

BAR_W, BAR_H = 360, 104
WAVE_BARS = 33


class WaveOverlay(QtWidgets.QWidget):
    """States: "rec" (live waveform) | "busy" (transcribing) |
    "ai" (Claude polishing) | "done" (flash the result, then hide)."""

    def __init__(self, settings: Settings, levels) -> None:
        super().__init__()
        self._settings = settings
        self._levels = levels  # Recorder's rolling amplitude envelope
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)  # don't steal focus
        self.resize(BAR_W, BAR_H)
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - BAR_W // 2, screen.bottom() - BAR_H - 56)
        self.phase = 0.0
        self.opacity = 0.0
        self.state = "rec"
        self.msg = ""
        self.smooth = np.zeros(WAVE_BARS, dtype=np.float32)  # eased bar heights
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)

    def start(self) -> None:
        self.state = "rec"
        self.opacity = 0.0
        self.setWindowOpacity(0.0)
        self.smooth[:] = 0.0
        self.show()
        self.timer.start(16)  # ~60 fps

    def set_stage(self, stage: str) -> None:
        self.state = stage

    def set_done(self, msg: str) -> None:
        self.state = "done"
        self.msg = msg
        self.update()
        QtCore.QTimer.singleShot(1100, self.stop)  # flash the result, then hide

    def stop(self) -> None:
        self.timer.stop()
        self.hide()

    def _tick(self) -> None:
        self.phase += 0.11
        if self.opacity < 1.0:
            self.opacity = min(1.0, self.opacity + 0.14)
            self.setWindowOpacity(self.opacity)
        # ease bar heights toward the live envelope so motion feels fluid
        env = np.array(self._levels, dtype=np.float32)
        target = np.interp(np.linspace(0, len(env) - 1, WAVE_BARS),
                           np.arange(len(env)), env)
        target = np.clip(target * 55.0, 0.04, 1.0)
        self.smooth += (target - self.smooth) * 0.35
        self.update()

    # ---- painting -------------------------------------------------------
    def paintEvent(self, _event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        body = QtCore.QRectF(14, 10, self.width() - 28, self.height() - 30)
        radius = body.height() / 2

        # soft drop shadow: stacked translucent rings below the pill
        painter.setPen(QtCore.Qt.NoPen)
        for i in range(10, 0, -1):
            painter.setBrush(QtGui.QColor(0, 0, 0, 4))
            painter.drawRoundedRect(
                body.adjusted(-i * 0.6, -i * 0.3 + 3, i * 0.6, i * 0.9 + 3),
                radius + i, radius + i)

        # glass body
        grad = QtGui.QLinearGradient(body.topLeft(), body.bottomLeft())
        grad.setColorAt(0.0, QtGui.QColor(26, 27, 34, 244))
        grad.setColorAt(1.0, QtGui.QColor(15, 16, 21, 244))
        painter.setBrush(grad)
        painter.drawRoundedRect(body, radius, radius)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 26), 1.0))
        painter.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        self._chips(painter, body)

        if self.state == "busy":
            self._label(painter, body, "Transcribing" + "." * (1 + int(self.phase * 2) % 3))
        elif self.state == "ai":
            self._label(painter, body, "Polishing" + "." * (1 + int(self.phase * 2) % 3))
        elif self.state == "done":
            self._label(painter, body, self.msg)
        else:
            self._wave(painter, body)
        painter.end()

    def _wave(self, painter, body) -> None:
        left, right = body.left() + 52, body.right() - 40
        mid = body.center().y()
        amp = body.height() * 0.62

        grad = QtGui.QLinearGradient(left, 0, right, 0)
        grad.setColorAt(0.0, QtGui.QColor(64, 224, 208))    # teal
        grad.setColorAt(0.5, QtGui.QColor(122, 162, 255))   # blue
        grad.setColorAt(1.0, QtGui.QColor(192, 132, 255))   # violet

        # faint guide line so silence still reads as "listening"
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 16), 1.0))
        painter.drawLine(QtCore.QPointF(left, mid), QtCore.QPointF(right, mid))
        painter.setPen(QtCore.Qt.NoPen)

        step = (right - left) / WAVE_BARS
        bar_w = step * 0.52
        for i in range(WAVE_BARS):
            x = left + (i + 0.5) * step
            flow = 0.55 + 0.45 * math.sin(self.phase * 2.1 + i * 0.55)
            bar_h = max(3.0, amp * float(self.smooth[i]) * flow)
            # glow pass then core bar
            painter.setBrush(QtGui.QColor(122, 162, 255, 26))
            painter.drawRoundedRect(
                QtCore.QRectF(x - bar_w, mid - bar_h / 2 - 2, bar_w * 2, bar_h + 4),
                bar_w, bar_w)
            painter.setBrush(grad)
            painter.drawRoundedRect(
                QtCore.QRectF(x - bar_w / 2, mid - bar_h / 2, bar_w, bar_h),
                bar_w / 2, bar_w / 2)

    def _chips(self, painter, body) -> None:
        # language chip, left side
        chip = QtCore.QRectF(body.left() + 12, body.center().y() - 10, 30, 20)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(255, 255, 255, 18))
        painter.drawRoundedRect(chip, 10, 10)
        painter.setPen(QtGui.QColor(255, 255, 255, 165))
        font = QtGui.QFont("Segoe UI", 8)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(chip, QtCore.Qt.AlignCenter, self._settings.language.upper())

        # mode dot (+ translate target), right side
        online = self._settings.mode == "online"
        dot_x = body.right() - 22
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(94, 222, 146) if online
                         else QtGui.QColor(255, 255, 255, 55))
        painter.drawEllipse(QtCore.QPointF(dot_x, body.center().y() - 6), 3.5, 3.5)
        if online and self._settings.translate != "off":
            target = self._settings.translate.split("-")[1].upper()
            painter.setPen(QtGui.QColor(255, 255, 255, 120))
            painter.drawText(QtCore.QRectF(dot_x - 16, body.center().y(), 32, 14),
                             QtCore.Qt.AlignCenter, "→" + target)

    def _label(self, painter, body, text: str) -> None:
        painter.setPen(QtGui.QColor(235, 236, 240, 235))
        font = QtGui.QFont("Segoe UI", 12)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(body, QtCore.Qt.AlignCenter, text)
