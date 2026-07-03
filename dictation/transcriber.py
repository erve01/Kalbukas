"""Local speech-to-text via faster-whisper (GPU float16, CPU int8 fallback).

Hardware support: CTranslate2 accelerates on NVIDIA/CUDA only. Everything
else — AMD GPUs, Intel, Apple Silicon — runs the int8 CPU path, so "auto"
picks a model size that stays responsive there.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys

import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.utils import download_model as _snapshot_download

# config.MODEL_DIR is read at call time, not import time — migration may
# repoint it when the legacy models folder can't be moved.
from . import config
from .config import SAMPLE_RATE, WHISPER_PROMPTS

log = logging.getLogger(__name__)


def cuda_available() -> bool:
    """True when an NVIDIA driver is present. Attempting a CUDA load without
    one (AMD / Apple / plain CPU boxes) wastes startup time on a doomed try."""
    if sys.platform == "darwin":
        return False
    lib = "nvcuda.dll" if sys.platform == "win32" else "libcuda.so.1"
    try:
        ctypes.CDLL(lib)
        return True
    except OSError:
        return False


def resolve_model_size(preference: str) -> str:
    if preference != "auto":
        return preference
    return config.GPU_DEFAULT_MODEL if cuda_available() else config.CPU_DEFAULT_MODEL


def _repo_dir(size: str) -> str:
    return os.path.join(config.MODEL_DIR,
                        "models--Systran--faster-whisper-%s" % size)


def model_is_downloaded(size: str) -> bool:
    snapshots = os.path.join(_repo_dir(size), "snapshots")
    if not os.path.isdir(snapshots):
        return False
    return any(os.path.isfile(os.path.join(snapshots, snap, "model.bin"))
               for snap in os.listdir(snapshots))


def download(size: str) -> None:
    """Blocking, resumable weight download (the only network use for models).
    Callers own the UI and the netlock state."""
    _snapshot_download(size, cache_dir=config.MODEL_DIR, local_files_only=False)


def downloaded_bytes(size: str) -> int:
    """Rough on-disk footprint of a (possibly partial) download — drives the
    progress bar without hooking huggingface_hub internals."""
    total = 0
    for root, _dirs, files in os.walk(_repo_dir(size)):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


class Transcriber:
    def __init__(self, model_size: str, warmup_language: str) -> None:
        self.model_size = model_size
        self.device = "cpu"
        if cuda_available():
            try:
                self._model = WhisperModel(model_size, device="cuda",
                                           compute_type="float16",
                                           download_root=config.MODEL_DIR,
                                           local_files_only=True)
                # cuDNN problems only surface on first use — warm up on 1s of
                # silence (also removes the first-dictation latency)
                segments, _ = self._model.transcribe(
                    np.zeros(SAMPLE_RATE, dtype=np.float32),
                    language=warmup_language, beam_size=1)
                list(segments)
                self.device = "cuda"
            except Exception as exc:
                log.warning("GPU load failed (%s) - falling back to CPU int8.", exc)
        if self.device == "cpu":
            self._model = WhisperModel(model_size, device="cpu",
                                       compute_type="int8",
                                       download_root=config.MODEL_DIR,
                                       local_files_only=True)
        log.info("Model '%s' on %s.", model_size,
                 "GPU (float16)" if self.device == "cuda" else "CPU (int8)")

    def transcribe(self, audio: np.ndarray, language: str) -> str:
        segments, _ = self._model.transcribe(
            audio, language=language, beam_size=5,
            vad_filter=True,                    # skip silence -> fewer hallucinations
            condition_on_previous_text=False,   # short clips: avoid repetition loops
            initial_prompt=WHISPER_PROMPTS[language],
        )
        return " ".join(s.text.strip() for s in segments).strip()
