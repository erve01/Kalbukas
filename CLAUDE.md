# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Kalbukas** — a Lithuanian/English dictation tool. Press the hotkey (default **F9**) to start recording (a floating waveform overlay reacts to your voice), press it again to stop — or let the configurable silence timeout stop it for you. The audio is transcribed locally with faster-whisper (GPU float16 on NVIDIA, CPU int8 everywhere else), cleaned up deterministically (fillers, stutter, hallucinated caption phrases), and the text is auto-pasted into the focused app or copied to the clipboard. When Whisper's confidence falls below the configurable threshold, a review dialog asks the user to confirm/fix the text before anything is sent to Claude or pasted. A **system tray icon** holds all settings (language LT/EN, output mode, translation, silence timeout, confidence check, model size, microphone, shortcut, API key, history), persisted in the per-user data dir. When an **Anthropic API key** is set, the transcription is additionally polished (and optionally translated LT↔EN) by a single Claude API call (`claude-opus-4-8`) that receives the user's recent dictations as terminology context — with automatic fallback to the local transcription on any API failure.

## Commands

```bash
# dev setup (Windows)
python -m venv venv && venv\Scripts\activate
pip install .            # or .[gpu] on an NVIDIA machine

# run (offers a one-time model download dialog on first start)
python main.py
python main.py --download   # headless model download

# packaging (see packaging/)
pip install .[build]
python packaging/make_icons.py                              # regenerate assets/
pyinstaller packaging/Kalbukas.spec --noconfirm       # CPU build
LD_GPU=1 pyinstaller packaging/Kalbukas.spec --noconfirm  # GPU build
ISCC packaging\installer.iss          # Windows installer (/DGPU for GPU)
bash packaging/make_dmg.sh            # macOS dmg (run on a Mac)
```

There is no lint or test tooling configured. `.github/workflows/release.yml` builds all installers on a `v*` tag push.

## File locations (per-user, never next to the code)

| What | Where (Windows) |
|---|---|
| settings.json, history.jsonl | `%LOCALAPPDATA%\Kalbukas\` |
| Whisper models | `%LOCALAPPDATA%\Kalbukas\models\` |
| app.log (rotating) + crash-*.txt | `%LOCALAPPDATA%\Kalbukas\Logs\` |
| Anthropic API key | Windows Credential Manager (`keyring`), **never a file** |

macOS uses `~/Library/Application Support/Kalbukas` and `~/Library/Logs/Kalbukas`. `config.migrate_legacy_files()` (called from `main.py`) still moves pre-rename ("LocalDictation") dirs, the old credential entry, and pre-1.0 script-side files on first run.

## Architecture

`main.py` is a thin entry point; everything lives in the `dictation/` package:

| Module | Responsibility |
|---|---|
| `bootstrap.py` | UTF-8 stdio, CUDA DLL registration (venv wheels or PyInstaller `_internal/nvidia`). **Must run before anything imports faster_whisper.** |
| `config.py` | Paths/constants, `Settings` dataclass (validated load, atomic save), keyring-backed `get_api_key()`/`set_api_key()`, confidence thresholds + silence-timeout choices. |
| `logsetup.py` | Rotating file log + console; `install_crash_handlers()` routes unhandled exceptions (all threads) to crash files + a dialog. |
| `audio.py` | `Recorder` + platform-aware mic enumeration (WASAPI→MME on Windows, Core Audio on macOS). Mics stored by **name**, not index. Tracks when voice was last heard (`silence_seconds()`) for the auto-stop. |
| `transcriber.py` | `cuda_available()` (driver probe — no blind CUDA attempts), `resolve_model_size()` ("auto" → large-v3 on GPU / medium on CPU), `model_is_downloaded()`, `download()`, `Transcriber` — returns a `Transcription` (text + 0..1 confidence), dropping segments Whisper flags as probable silence. Model loads never need network (`local_files_only=True` everywhere). |
| `textclean.py` | Deterministic pre-AI cleanup: non-lexical fillers, 3+ word stutter loops, punctuation debris, whole-transcript hallucinations ("Ačiū, kad žiūrėjote"). Judgement calls are left to Claude. |
| `enhancer.py` | One Claude call fixing errors/translating, fed the last few dictations as terminology context. **Returns None on any failure — never lose a dictation.** |
| `history.py` | JSONL history capped at 500, atomic writes; tray can pause saving; `recent_texts()` feeds the enhancer context. |
| `hotkey.py` | pynput hotkey strings + `HotkeyListener`. |
| `updates.py` | GitHub-releases version check (enabled once `config.RELEASES_API_URL` is set). |
| `app.py` | `Controller` (owns model lifecycle: background load, hot swap; dictation flow: transcribe → clean → confidence gate → optional review → optional Claude → paste) + `main()` (single-instance QLockFile, tray-first startup). |
| `ui/` | `overlay.py` (waveform pill), `tray.py` (settings menu, About, update check), `review_dialog.py` (low-confidence confirm/fix/discard), `download_dialog.py` (first-run model download), `shortcut_dialog.py`, `history_window.py`. |

### Startup model (the main thing to understand)

`main()` shows the **tray immediately**; the Whisper model loads on a background thread (`Controller.start`) in parallel with the mic open. Nothing at startup may block or die: a missing model triggers the download dialog, a missing mic degrades gracefully (balloon + recovery on next hotkey press or via the tray Microphone menu). Model switches from the tray hot-swap the same way (`Controller.change_model`).

### Threading model

- **Qt main thread** — owns all widgets, runs `app.exec()`. Tray/dialog handlers run here.
- **pynput threads** — the global hotkey fires `Controller.toggled` (a Qt signal) to hop onto the main thread; never touch widgets from there.
- **loader threads** — model load / mic open at startup and on hot swap; results come back via `model_ready` / `notify` signals.
- **worker thread** — one short-lived daemon per dictation (`Controller._process`); a second one runs `_finalize` when the low-confidence review dialog interrupts the flow. Both wrapped in try/except so the overlay can never get stuck on "busy".
- **sounddevice callback thread** — `Recorder._callback` appends frames/levels while `recording` is true. Cross-thread state stays flag reads and appends (GIL-safe).

### Gotchas that keep coming back

- **Import order:** CUDA DLL dirs must be registered before `faster_whisper`/CTranslate2 import, and **PySide6 must be imported *after* faster_whisper** (Qt-first segfaults at CUDA model load on Windows). Runtime order is safe — the QApplication may exist before the model loads; only the *import* order matters (verified empirically).
- **Bluetooth mics (Jabra):** they drop off Windows' device list when sleeping. `Recorder.open()` retries with re-enumeration; `_try_open` must `start()` the stream to validate. Never use WDM-KS.
- **Windows legacy code page:** bootstrap forces UTF-8 stdio; paste **before** logging in `_on_finished`.
- `app.setQuitOnLastWindowClosed(False)` — tray app; closing the history window must not exit.
- `container`-style Qt6 differences: `QAction`/`QActionGroup` live in QtGui, signals are `QtCore.Signal`.
- Killing the app from git-bash (`kill $!`) can orphan the real process — use `taskkill //IM` when testing; the QLockFile single-instance guard is what surfaces the confusion.

## Git

- `settings.json`/`history.jsonl`/`models/` are legacy-ignored; user data now lives outside the repo entirely.
- Never create a commit or push without being asked.
