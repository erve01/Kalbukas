# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Kalbukas (Windows exe dir / macOS .app).

Build from the repo root:
    venv/Scripts/pyinstaller packaging/Kalbukas.spec --noconfirm

Windows GPU variant (bundles the CUDA 12 runtime DLLs, ~1 GB larger):
    LD_GPU=1 venv/Scripts/pyinstaller packaging/Kalbukas.spec --noconfirm

The Whisper models are NOT bundled — the app offers a one-time download on
first run, keeping the installer small.
"""

import os
import sys
import sysconfig

from PyInstaller.utils.hooks import collect_data_files

ROOT = os.path.dirname(os.path.abspath(SPECPATH))  # SPECPATH = packaging/
sys.path.insert(0, ROOT)

import dictation  # noqa: E402 — version single-source

APP_VERSION = dictation.__version__
GPU = os.environ.get("LD_GPU") == "1"
NAME = "Kalbukas" + ("-GPU" if GPU else "")

datas = collect_data_files("faster_whisper")  # silero VAD assets

binaries = []
if GPU and sys.platform == "win32":
    nvidia_dir = os.path.join(sysconfig.get_paths()["purelib"], "nvidia")
    for pkg in sorted(os.listdir(nvidia_dir)):
        bin_dir = os.path.join(nvidia_dir, pkg, "bin")
        if os.path.isdir(bin_dir):
            binaries += [(os.path.join(bin_dir, dll), "nvidia/%s/bin" % pkg)
                         for dll in os.listdir(bin_dir)
                         if dll.lower().endswith(".dll")]

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    excludes=["tkinter", "IPython", "pytest", "setuptools"],
)
pyz = PYZ(a.pure)

version_resource = None
if sys.platform == "win32":
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable,
        VarFileInfo, VarStruct, VSVersionInfo)

    parts = tuple(int(p) for p in APP_VERSION.split(".")) + (0,)
    version_resource = VSVersionInfo(
        ffi=FixedFileInfo(filevers=parts, prodvers=parts),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("ProductName", "Kalbukas"),
                StringStruct("FileDescription", "Kalbukas — offline speech to text"),
                StringStruct("ProductVersion", APP_VERSION),
                StringStruct("FileVersion", APP_VERSION),
                StringStruct("LegalCopyright", "© 2026 Ernestas"),
                StringStruct("OriginalFilename", NAME + ".exe"),
            ])]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ])

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    console=False,                    # windowed: no console flash
    icon=os.path.join(ROOT, "assets", "icon.ico"),
    version=version_resource,
)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Kalbukas.app",
        icon=os.path.join(ROOT, "assets", "icon.icns"),
        bundle_identifier="lt.ernestas.kalbukas",
        version=APP_VERSION,
        info_plist={
            "LSUIElement": True,  # tray app: no Dock icon
            "NSMicrophoneUsageDescription":
                "Kalbukas records your voice to transcribe it on this Mac.",
            "NSAppleEventsUsageDescription":
                "Kalbukas pastes the transcribed text into the app you are using.",
            "NSHighResolutionCapable": True,
        },
    )
