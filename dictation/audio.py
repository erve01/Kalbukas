"""Microphone capture: device discovery, stream lifecycle, level envelope."""

from __future__ import annotations

import collections
import logging
import sys
import threading
import time
from typing import Optional

import numpy as np
import sounddevice as sd

from .config import SAMPLE_RATE

log = logging.getLogger(__name__)

ENV_LEN = 64  # samples in the rolling amplitude envelope

# mean |amplitude| above which a block counts as voice rather than room
# noise — drives the silence auto-stop (speech typically lands at 0.02+)
VOICE_LEVEL = 0.012

# A live input stream fires its callback continuously; if none has arrived for
# this long the device was pulled mid-session (earbuds cased, headset off,
# unplugged) even though the stream object still exists.
STREAM_STALL_SECONDS = 1.0

# Host APIs per platform, in preference order. Windows: WASAPI (full names,
# connected devices only), then MME (Bluetooth mics vanish from WASAPI while
# the headset is in music-only mode); WDM-KS is never used — it keeps dead
# endpoints of sleeping headsets.
_HOST_APIS = {"win32": ("WASAPI", "MME"), "darwin": ("Core Audio",)}


def list_microphones() -> list[tuple[int, str]]:
    """Input devices as (index, name), from the platform's preferred host API."""
    devices = sd.query_devices()
    apis = sd.query_hostapis()

    def inputs(api_substr: Optional[str]) -> list[tuple[int, str]]:
        api_idxs = {i for i, h in enumerate(apis)
                    if api_substr is None or api_substr in h["name"]}
        return [(i, d["name"]) for i, d in enumerate(devices)
                if d["max_input_channels"] > 0 and d["hostapi"] in api_idxs
                and not d["name"].startswith("Microsoft Sound Mapper")]

    for api in _HOST_APIS.get(sys.platform, ()):
        found = inputs(api)
        if found:
            return found
    # unknown platform (or nothing matched): any input-capable device
    return inputs(None) if sys.platform not in _HOST_APIS else []


def find_mic_index(name: str) -> Optional[int]:
    """Saved mic name -> current device index (None = system default).
    Names are stored instead of indices because indices shuffle whenever a
    device connects or disconnects."""
    if not name:
        return None
    for index, device_name in list_microphones():
        if device_name == name:
            return index
    return None


# PortAudio snapshots the device list at init and never rescans on its own, so
# a mic connected after startup stays invisible until it re-inits. Serialized:
# it mutates PortAudio-global state that the startup open() retry loop also
# touches, and concurrent terminate/init can crash the library.
_pa_lock = threading.Lock()


def refresh_devices() -> None:
    """Force PortAudio to re-enumerate hardware. Drops every open stream, so
    callers must have none (a live stream already sees its own device)."""
    with _pa_lock:
        sd._terminate()
        sd._initialize()


class Recorder:
    """Owns the input stream and the raw frames of the current take.

    The sounddevice callback runs on its own thread; ``recording``,
    ``_frames`` and ``levels`` are the only cross-thread state — kept to
    flag reads and appends, which are safe under the GIL.
    """

    def __init__(self) -> None:
        self.recording = False
        self.levels: collections.deque = collections.deque([0.0] * ENV_LEN,
                                                           maxlen=ENV_LEN)
        self._frames: list[np.ndarray] = []
        self._stream: Optional[sd.InputStream] = None
        self._last_voice = 0.0  # monotonic time voice was last heard
        self._last_callback = 0.0  # monotonic time the audio callback last ran

    @property
    def ready(self) -> bool:
        """True only when a stream is open *and* actually delivering audio.
        A Bluetooth device pulled mid-session (earbuds back in the case, headset
        turned off) leaves the stream object in place but silent — report that
        as not ready so the hotkey path re-acquires the reconnected device."""
        stream = self._stream
        if stream is None:
            return False
        try:
            if not stream.active:
                return False
        except Exception:
            return False
        return time.monotonic() - self._last_callback < STREAM_STALL_SECONDS

    # ---- capture ------------------------------------------------------
    def start_take(self) -> None:
        self._frames = []
        self.levels.extend([0.0] * ENV_LEN)
        self._last_voice = time.monotonic()  # the take starts the clock
        self.recording = True

    def finish_take(self) -> np.ndarray:
        self.recording = False
        if not self._frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self._frames, axis=0).flatten()

    def silence_seconds(self) -> float:
        """Seconds since voice was last heard in the current take."""
        return time.monotonic() - self._last_voice

    def _callback(self, indata, _frames, _time, _status) -> None:
        self._last_callback = time.monotonic()  # liveness — fires even when idle
        if self.recording:
            self._frames.append(indata.copy())
            level = float(np.abs(indata).mean())
            self.levels.append(level)
            if level > VOICE_LEVEL:
                self._last_voice = time.monotonic()

    # ---- stream lifecycle ----------------------------------------------
    def _acquire(self, preferred_name: str, include_all: bool) -> bool:
        """One pass at getting a stream: the saved mic, then the system
        default, then (when ``include_all``) any input-capable device — a
        reconnected Bluetooth headset is frequently present but *not* the
        default. Installs the first that opens and returns True."""
        candidates: list[Optional[int]] = []
        preferred = find_mic_index(preferred_name)
        if preferred is not None:
            candidates.append(preferred)
        candidates.append(None)  # None = system default
        if include_all:
            candidates += [i for i, d in enumerate(sd.query_devices())
                           if d["max_input_channels"] > 0]
        for device in candidates:
            stream = self._try_open(device)
            if stream is not None:
                old, self._stream = self._stream, stream
                self._close(old)
                if device is not None:
                    log.info("  using microphone: %s",
                             sd.query_devices(device)["name"])
                return True
        return False

    def open(self, preferred_name: str, retries: int = 15) -> None:
        """Bluetooth mics drop off Windows' device list for a few seconds
        after a stream closes (profile renegotiation) — retry the preferred
        and default devices, re-enumerating each time, before falling back
        to any input-capable one."""
        for attempt in range(retries):
            if self._acquire(preferred_name, include_all=attempt >= 5):
                return
            log.info("  no microphone available - retrying (%d/%d)",
                     attempt + 1, retries)
            time.sleep(2)
            refresh_devices()
        raise RuntimeError("No microphone found - connect one and restart.")

    def reopen(self, preferred_name: str) -> bool:
        """On-demand recovery when the stream is gone or dead (mic enabled after
        a mic-less start, or earbuds cased then taken out again): drop any stale
        stream, re-enumerate, then try the saved mic, the default, and finally
        any input device — one quick pass, no blocking. A device still switching
        to its handsfree profile may need a second call."""
        self.close()  # a dead stream must go before rescan() can re-enumerate
        self.rescan()
        return self._acquire(preferred_name, include_all=True)

    def switch(self, name: str) -> Optional[str]:
        """Switch to the named device ("" = system default). Returns an error
        message, or None on success. The new stream is started before the old
        one closes so recording never has zero streams."""
        device = find_mic_index(name)
        if name and device is None:
            return "'%s' is no longer connected." % name
        stream = self._try_open(device)
        if stream is None:
            return "Could not open '%s'." % (name or "system default")
        old, self._stream = self._stream, stream
        self._close(old)
        return None

    def rescan(self) -> None:
        """Make a mic connected after startup visible to list_microphones()/
        switch(). No-op while a stream is live: the re-init would drop it (and
        knock Bluetooth mics offline for seconds), and its device is already
        enumerable anyway. Safe after a mic-less start, where no stream exists."""
        if self._stream is None:
            refresh_devices()

    def close(self) -> None:
        self._close(self._stream)
        self._stream = None

    def _try_open(self, device: Optional[int]) -> Optional[sd.InputStream]:
        stream = None
        try:
            stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                    dtype="float32", callback=self._callback,
                                    device=device)
            stream.start()  # disconnected BT endpoints open fine but fail here
            self._last_callback = time.monotonic()  # grace until first callback
            return stream
        except sd.PortAudioError:
            if stream is not None:
                self._close(stream)
            return None

    @staticmethod
    def _close(stream: Optional[sd.InputStream]) -> None:
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
