"""Render the app icon (waveform glyph on a dark tile) and emit
assets/icon.png, icon.ico (Windows) and icon.icns (macOS).

Run from the repo root:  python packaging/make_icons.py
"""

import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"  # render without a window

from PySide6 import QtCore, QtGui  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
SIZE = 1024


def render() -> QtGui.QImage:
    image = QtGui.QImage(SIZE, SIZE, QtGui.QImage.Format_ARGB32)
    image.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)

    # dark rounded tile
    tile = QtCore.QRectF(SIZE * 0.04, SIZE * 0.04, SIZE * 0.92, SIZE * 0.92)
    bg = QtGui.QLinearGradient(tile.topLeft(), tile.bottomLeft())
    bg.setColorAt(0.0, QtGui.QColor(30, 31, 40))
    bg.setColorAt(1.0, QtGui.QColor(13, 14, 19))
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(bg)
    painter.drawRoundedRect(tile, SIZE * 0.21, SIZE * 0.21)

    # waveform bars, teal -> blue -> violet (matches the tray/overlay)
    grad = QtGui.QLinearGradient(tile.left(), 0, tile.right(), 0)
    grad.setColorAt(0.0, QtGui.QColor(64, 224, 208))
    grad.setColorAt(0.5, QtGui.QColor(122, 162, 255))
    grad.setColorAt(1.0, QtGui.QColor(192, 132, 255))
    painter.setBrush(grad)
    heights = (0.30, 0.52, 0.74, 0.52, 0.30)
    bar_w = SIZE * 0.088
    step = SIZE * 0.148
    first_x = SIZE / 2 - (len(heights) - 1) / 2 * step - bar_w / 2
    for i, rel in enumerate(heights):
        bar_h = SIZE * rel
        painter.drawRoundedRect(
            QtCore.QRectF(first_x + i * step, (SIZE - bar_h) / 2, bar_w, bar_h),
            bar_w / 2, bar_w / 2)
    painter.end()
    return image


def main() -> None:
    os.makedirs(ASSETS, exist_ok=True)
    png_path = os.path.join(ASSETS, "icon.png")
    render().save(png_path)

    from PIL import Image

    art = Image.open(png_path)
    art.save(os.path.join(ASSETS, "icon.ico"),
             sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    art.save(os.path.join(ASSETS, "icon.icns"))
    print("Wrote icon.png / icon.ico / icon.icns to", ASSETS)


if __name__ == "__main__":
    sys.exit(main())
