"""Application wiring: controller, hotkey, tray, overlay, Qt event loop.

Threading model — three concurrent threads coordinate through Qt signals:

* Qt main thread     — owns all widgets; runs ``app.exec()``.
* pynput threads     — the global hotkey fires ``Controller.toggled``.
* worker thread      — one short-lived daemon per dictation runs Whisper
                       (and Claude when an API key is set), then emits
                       ``finished``.

Never touch widgets from the pynput/worker threads — always go through the
Controller's signals.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time

import numpy as np
import pyperclip
from pynput import keyboard

# Import order is load-bearing: ctranslate2 (via .transcriber / faster_whisper)
# must load its DLLs before Qt loads its own — the reverse order segfaults
# at CUDA model load on Windows. Keep every PySide6 import below this block.
from . import enhancer, hotkey, logsetup, textclean
from .audio import Recorder
from .config import (APP_DISPLAY_NAME, CONFIDENCE_THRESHOLDS, DATA_DIR,
                     ENHANCER_CONTEXT_ENTRIES, SAMPLE_RATE, Settings)
from .history import History
from .hotkey import HotkeyListener
from .transcriber import Transcriber, model_is_downloaded, resolve_model_size

from PySide6 import QtCore, QtWidgets

from .ui.download_dialog import DownloadDialog
from .ui.overlay import WaveOverlay
from .ui.review_dialog import ReviewDialog
from .ui.tray import Tray

log = logging.getLogger(__name__)


def paste_text(text: str) -> None:
    kb = keyboard.Controller()
    pyperclip.copy(text)
    time.sleep(0.05)
    modifier = keyboard.Key.cmd if sys.platform == "darwin" else keyboard.Key.ctrl
    with kb.pressed(modifier):
        kb.press("v")
        kb.release("v")


class Controller(QtCore.QObject):
    """Bridges the pynput/worker threads to the Qt main thread via signals,
    and owns the model lifecycle (background load, hot swap)."""

    toggled = QtCore.Signal()
    staged = QtCore.Signal(str)
    review = QtCore.Signal(str, float)  # shaky transcription, its confidence
    finished = QtCore.Signal(str, str)  # final text, local transcription
    failed = QtCore.Signal(str)         # worker error, short user message
    notify = QtCore.Signal(str, str)    # tray balloon: title, message
    model_ready = QtCore.Signal()

    def __init__(self, settings: Settings, recorder: Recorder,
                 history: History, overlay: WaveOverlay) -> None:
        super().__init__()
        self._settings = settings
        self._recorder = recorder
        self._history = history
        self._overlay = overlay
        self.transcriber: Transcriber | None = None  # set once loaded
        self._loading = False
        self.hotkeys = HotkeyListener(settings.hotkey, self.toggled.emit)
        self._silence_timer = QtCore.QTimer(self)
        self._silence_timer.setInterval(250)
        self._silence_timer.timeout.connect(self._check_silence)
        self.toggled.connect(self._on_toggle)
        self.staged.connect(self._overlay.set_stage)
        self.review.connect(self._on_review)
        self.finished.connect(self._on_finished)
        self.failed.connect(self._overlay.set_done)

    def set_hotkey(self, value: str) -> None:
        self._settings.hotkey = value
        self._settings.save()
        self.hotkeys.set_hotkey(value)
        log.info("Shortcut set to %s", hotkey.display(value))

    def shutdown(self) -> None:
        self.hotkeys.stop()
        self._recorder.close()

    @property
    def loading(self) -> bool:
        return self._loading

    # ---- model lifecycle --------------------------------------------------
    def start(self, model_size: str) -> None:
        """Kick off the background model load and mic open in parallel —
        the tray must be usable from the first second."""
        self._loading = True
        threading.Thread(target=self._open_mic_bg, daemon=True).start()
        threading.Thread(target=self._load_model_bg, args=(model_size,),
                         daemon=True).start()

    def change_model(self, preference: str) -> bool:
        """Hot-swap to the model for ``preference`` (tray, main thread).
        Returns False when the change cannot proceed (caller reverts)."""
        size = resolve_model_size(preference)
        if self._loading:
            self.notify.emit("Model", "Still loading a model — try again "
                                      "in a moment.")
            return False
        if self.transcriber is not None and self.transcriber.model_size == size:
            return True
        if not model_is_downloaded(size):
            if DownloadDialog(size).exec() != QtWidgets.QDialog.Accepted:
                return False
        self._loading = True
        threading.Thread(target=self._load_model_bg, args=(size,),
                         daemon=True).start()
        return True

    def _load_model_bg(self, model_size: str) -> None:
        try:
            log.info("Loading model '%s'...", model_size)
            self.transcriber = Transcriber(
                model_size, warmup_language=self._settings.language)
            self.model_ready.emit()
            log.info("Ready. Press %s to dictate.",
                     hotkey.display(self._settings.hotkey))
        except Exception as exc:
            log.exception("Model load failed")
            self.notify.emit(
                "Speech model failed to load",
                "%s — pick another model in the tray menu, or restart." % exc)
        finally:
            self._loading = False

    def _open_mic_bg(self) -> None:
        try:
            self._recorder.open(self._settings.mic)
        except RuntimeError:
            self.notify.emit(
                "No microphone found",
                "Connect one, then pick it in the tray's Microphone menu.")

    # ---- dictation flow ---------------------------------------------------
    def _on_toggle(self) -> None:
        if not self._recorder.recording:
            if self.transcriber is None:
                self.notify.emit("Not ready yet", "The speech model is still "
                                 "loading — try again in a few seconds.")
                return
            if not self._recorder.ready and not self._reopen_mic():
                return
            self._recorder.start_take()
            self._overlay.start()
            if self._settings.silence_timeout:
                self._silence_timer.start()
            log.info("* Recording...")
        else:
            self._silence_timer.stop()
            audio = self._recorder.finish_take()
            self._overlay.set_stage("busy")
            log.info("... transcribing")
            threading.Thread(target=self._process, args=(audio,),
                             daemon=True).start()

    def _check_silence(self) -> None:
        """Main thread (QTimer): end the take after the configured stretch
        of silence — a hands-free alternative to the second hotkey press."""
        timeout = self._settings.silence_timeout
        if not timeout or not self._recorder.recording:
            self._silence_timer.stop()
            return
        if self._recorder.silence_seconds() >= timeout:
            log.info("  auto-stop after %ds of silence", timeout)
            self._on_toggle()

    def _reopen_mic(self) -> bool:
        """Recover the mic after a mic-less start: re-enumerate, then try the
        saved mic, the system default, and finally any input-capable device —
        a Bluetooth headset often isn't the default when it reconnects. One
        still switching to its handsfree profile may need a second press."""
        if self._recorder.reopen(self._settings.mic):
            return True
        self.notify.emit(
            "Microphone",
            "Couldn't open a microphone yet. If you just connected one, press "
            "%s again in a moment, or pick it in the tray's Microphone menu."
            % hotkey.display(self._settings.hotkey))
        return False

    def _process(self, audio: np.ndarray) -> None:
        """Worker thread: local transcription + deterministic cleanup, then
        either the low-confidence review or straight to finalization."""
        text = ""
        try:
            if audio.size:
                log.info("  captured %.1fs, peak level %.3f",
                         audio.size / SAMPLE_RATE, float(np.abs(audio).max()))
                result = self.transcriber.transcribe(audio, self._settings.language)
                text = textclean.clean(result.text, self._settings.language)
                if text != result.text:
                    log.info("  cleanup: %r -> %r", result.text, text)
                threshold = CONFIDENCE_THRESHOLDS[self._settings.confidence]
                if text and result.confidence < threshold:
                    log.info("  confidence %.2f < %.2f - asking the user",
                             result.confidence, threshold)
                    self.review.emit(text, result.confidence)
                    return
        except Exception:
            # never leave the overlay stuck on "busy" — report and recover
            log.exception("Dictation failed")
            self.failed.emit("Error — see log")
            return
        self._finalize(text)

    def _on_review(self, text: str, confidence: float) -> None:
        """Main thread: the transcription was shaky — nothing goes to Claude
        or the target app until the user confirms (and can fix) the text."""
        self._overlay.stop()
        confirmed = ReviewDialog.get_text(text, confidence)
        if confirmed is None:
            log.info("-> (discarded at review)")
            return
        # let focus return to the target app before a paste can fire
        QtCore.QTimer.singleShot(200, lambda: threading.Thread(
            target=self._finalize, args=(confirmed,), daemon=True).start())

    def _finalize(self, text: str) -> None:
        """Worker thread: optional AI cleanup of the confirmed local text."""
        local = text
        try:
            if text and self._settings.effective_api_key:
                self.staged.emit("ai")
                context = self._history.recent_texts(ENHANCER_CONTEXT_ENTRIES)
                polished = enhancer.enhance(text, self._settings, context)
                if polished:
                    text = polished
        except Exception:
            log.exception("Dictation failed")
            self.failed.emit("Error — see log")
            return
        self.finished.emit(text, local)

    def _on_finished(self, text: str, raw: str) -> None:
        if not text:
            log.info("-> (no speech detected)")
            self._overlay.set_done("No speech")
            return
        if self._settings.output == "paste":
            paste_text(text + " ")  # paste first — a logging failure must not eat the dictation
            done_msg = "Done ✓"
        else:
            pyperclip.copy(text)
            done_msg = "Copied ✓"
        log.info("-> %s", text)
        if self._settings.save_history:
            self._history.add(text=text, raw=raw, settings=self._settings)
        self._overlay.set_done(done_msg)


def _ensure_app() -> QtWidgets.QApplication:
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)  # tray app: windows must not exit
    return app


def _fatal(message: str) -> None:
    """Show a startup error to the user (a packaged app has no console)."""
    log.error("Startup aborted: %s", message)
    _ensure_app()
    QtWidgets.QMessageBox.critical(
        None, APP_DISPLAY_NAME,
        "%s\n\nThe log file may have more detail:\n%s" % (message, logsetup.LOG_FILE))
    sys.exit(1)


def main() -> None:
    logsetup.init()
    logsetup.install_crash_handlers()

    # a second instance would fight over the hotkey and the model
    lock = QtCore.QLockFile(os.path.join(DATA_DIR, "app.lock"))
    if not lock.tryLock(0):
        log.info("Another instance holds the lock - exiting.")
        _ensure_app()
        QtWidgets.QMessageBox.information(
            None, APP_DISPLAY_NAME,
            "%s is already running — look for the waveform icon in the "
            "system tray." % APP_DISPLAY_NAME)
        sys.exit(0)

    settings = Settings.load()

    model_size = resolve_model_size(settings.model)
    if not model_is_downloaded(model_size):
        _ensure_app()
        if DownloadDialog(model_size).exec() != QtWidgets.QDialog.Accepted:
            sys.exit(0)

    app = _ensure_app()

    if sys.platform == "darwin" and not settings.mac_permissions_ack:
        QtWidgets.QMessageBox.information(
            None, APP_DISPLAY_NAME,
            "macOS needs your permission for dictation to work:\n\n"
            "•  Microphone — to record your voice\n"
            "•  Input Monitoring — for the global shortcut\n"
            "•  Accessibility — to paste text into other apps\n\n"
            "Grant these in System Settings → Privacy & Security when macOS "
            "asks. If the shortcut or paste still does not work, restart "
            "the app after granting.")
        settings.mac_permissions_ack = True
        settings.save()

    # tray first, model + mic in the background — startup must feel instant
    recorder = Recorder()
    overlay = WaveOverlay(settings, recorder.levels)
    history = History()
    controller = Controller(settings, recorder, history, overlay)
    tray = Tray(app, settings, recorder, history, controller)
    controller.notify.connect(
        lambda title, message: tray.icon.showMessage(
            title, message, QtWidgets.QSystemTrayIcon.Information, 5000))
    controller.model_ready.connect(tray.on_model_ready)
    tray.set_status("Loading speech model…")
    controller.start(model_size)

    log.info("Tray ready. Press %s to dictate (%s) once the model is up.",
             hotkey.display(settings.hotkey), settings.language.upper())
    exit_code = app.exec()
    controller.shutdown()
    sys.exit(exit_code)
