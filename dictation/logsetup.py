"""Logging and crash reporting.

A packaged windowed app has no console — every message and traceback would
vanish. Everything therefore also goes to a rotating log file, and unhandled
exceptions write a crash report the user can find and send.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import platform
import sys
import threading
import time
import traceback

from . import __version__
from .config import APP_DISPLAY_NAME, LOG_DIR

log = logging.getLogger(__name__)

LOG_FILE = os.path.join(LOG_DIR, "app.log")


def init() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if sys.stderr is not None:  # windowed builds have no console streams
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(console)
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(file_handler)
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)
    log.info("%s %s | Python %s | %s", APP_DISPLAY_NAME, __version__,
             platform.python_version(), platform.platform())


def install_crash_handlers() -> None:
    """Route unhandled exceptions (main thread, Qt slots, worker threads)
    to a crash file + dialog. A custom sys.excepthook also stops Qt
    from qFatal-aborting the process on exceptions raised inside slots."""
    sys.excepthook = _handle
    threading.excepthook = lambda args: _handle(
        args.exc_type, args.exc_value, args.exc_traceback)


def _handle(exc_type, exc_value, exc_tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    path: str | None = os.path.join(
        LOG_DIR, "crash-%s.txt" % time.strftime("%Y%m%d-%H%M%S"))
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("%s %s | Python %s | %s\n\n%s" % (
                APP_DISPLAY_NAME, __version__, platform.python_version(),
                platform.platform(), detail))
    except OSError:
        path = None
    logging.getLogger("crash").critical("Unhandled exception:\n%s", detail)
    _show_dialog(path, exc_value)


def _show_dialog(path: str | None, exc_value) -> None:
    # widgets are only safe on the Qt main thread, and only once the
    # QApplication exists — otherwise the crash file + log must suffice
    if threading.current_thread() is not threading.main_thread():
        return
    from PySide6 import QtWidgets  # deferred: a crash can happen before Qt loads

    if QtWidgets.QApplication.instance() is None:
        return
    QtWidgets.QMessageBox.critical(
        None, APP_DISPLAY_NAME,
        "Something went wrong:\n%s\n\nA crash report was saved to:\n%s"
        % (exc_value, path or "(the report could not be saved)"))
