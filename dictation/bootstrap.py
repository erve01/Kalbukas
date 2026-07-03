"""Process-level setup that must run before any heavy import.

Import order is load-bearing: the CUDA DLL directories must be registered
before CTranslate2 first loads cublas/cudnn. Model loads never touch the
network regardless — every WhisperModel call passes local_files_only=True.
"""

import os
import sys


def apply() -> None:
    _force_utf8_stdio()
    # plain-file cache (no symlink privilege on Windows) is fine — quiet the hint
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    if sys.platform == "win32":
        _register_cuda_dlls()


def _force_utf8_stdio() -> None:
    # Windows pipes default to the legacy code page, which can't encode
    # Lithuanian text — a failed print inside a Qt slot aborts the whole app.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            stream.reconfigure(encoding="utf-8", errors="replace")


def _register_cuda_dlls() -> None:
    # CUDA DLLs ship in the nvidia-* wheels (no system CUDA install) — in a
    # PyInstaller build they are bundled under _internal/nvidia instead.
    # Register them so CTranslate2 can load cublas/cudnn.
    if getattr(sys, "frozen", False):
        nvidia_dir = os.path.join(sys._MEIPASS, "nvidia")
    else:
        import sysconfig

        nvidia_dir = os.path.join(sysconfig.get_paths()["purelib"], "nvidia")
    if not os.path.isdir(nvidia_dir):
        return
    for pkg in os.listdir(nvidia_dir):
        bin_dir = os.path.join(nvidia_dir, pkg, "bin")
        if os.path.isdir(bin_dir):
            os.add_dll_directory(bin_dir)
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ["PATH"]
