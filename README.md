# Kalbukas

Press a hotkey, speak Lithuanian or English, press it again — your words are
transcribed **locally** (OpenAI Whisper via faster-whisper) and pasted into
whatever app has focus. A floating waveform overlay reacts to your voice while
you talk.

With an Anthropic API key set, the transcribed text (never the audio) is
additionally sent to Claude for cleanup — misheard words, grammar,
punctuation — and optional LT↔EN translation.

## Features

- **F9 to dictate** (configurable shortcut) — works system-wide, pastes into the focused app or copies to clipboard
- **Fully local transcription** — Whisper `large-v3` on your GPU (NVIDIA, automatic) or CPU
- **Automatic transcript cleanup** — filler sounds ("uh", "um", "ėė"), stutter loops and Whisper's silence artifacts are stripped before the text is used
- **Confidence check** — when Whisper isn't sure it heard right, a small dialog lets you confirm or fix the text before it goes anywhere
- **Silence auto-stop** — optionally end the take after 5/10/15 s of silence, no second key press needed
- **AI cleanup (optional)** — one Claude API call fixes misrecognized words using your recent dictations as context; falls back to the local transcription on any failure
- **Translation** — LT → EN or EN → LT (uses Claude, needs an API key)
- **Dictation history** — last 500 dictations, browsable/copyable from the tray
- **System tray settings** — language, output, translation, silence timeout, confidence check, model, microphone, shortcut, API key

## Requirements

- Windows 10/11 (primary target), Python 3.10+
- A microphone
- ~3 GB disk for the Whisper `large-v3` model
- Optional: NVIDIA GPU (much faster transcription)
- Optional: an [Anthropic API key](https://console.anthropic.com/) for AI cleanup/translation

## Install

```bash
git clone <this repo>
cd local_dictation_ui
python -m venv venv
venv\Scripts\activate
pip install .            # or  pip install .[gpu]  on an NVIDIA machine

# One-time model download (~3 GB, needs internet) — also offered on first run:
python main.py --download
```

## Run

```bash
venv\Scripts\activate
python main.py
```

Wait for `Ready.` in the console (the model takes ~15 s to load), then:

1. Press **F9** — the waveform pill appears; speak.
2. Press **F9** again — the text is transcribed and pasted at your cursor.

All settings live in the **system tray icon** (right-click it):

| Menu | What it does |
|---|---|
| Language | Lithuanian or English transcription |
| Output | Auto-paste into the focused app, or clipboard only |
| Translate | LT → EN / EN → LT (needs an API key) |
| Stop recording on silence | End the take automatically after 5/10/15 s of silence |
| Ask before using unclear text | How unsure Whisper must be before you're asked to confirm the text |
| Model | Whisper model size (auto/large/medium/small) |
| Microphone | Pick a specific input device (refreshes live) |
| Change shortcut… | Press any key/combo to make it the new dictation hotkey |
| Set API key… | Paste your Anthropic API key for AI cleanup and translation |
| History… | Browse and copy your last 500 dictations |

Settings and history live in the per-user data dir
(`%LOCALAPPDATA%\Kalbukas` on Windows); the API key is stored in the OS
credential store, never in a file.

## Privacy

- Transcription always runs **locally** — audio never leaves your machine.
- With an API key set, only the transcribed *text* (plus your last few
  dictations, as correction context) is sent to the Anthropic API for
  cleanup/translation. Remove the key to keep everything on-device.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `No microphone found` at startup | Windows sees no input device. Wake your Bluetooth headset (take it out of the case), or plug in a mic, then restart. |
| Every dictation says "No speech" | The app is bound to a dead device — common when a Bluetooth headset went to sleep *after* startup. Pick the mic explicitly in tray → Microphone, or restart. |
| `GPU load failed … falling back to CPU` | The CUDA wheels aren't installed (see Install) or the GPU is busy. The app still works, just slower. |
| Text pastes garbled diacritics | Make sure the target app accepts Ctrl+V paste; try Output → Clipboard only and paste manually. |
| The confirm dialog appears too often | Lower the bar in tray → "Ask before using unclear text" (or pick a larger Whisper model — small models are less sure). |
| AI cleanup does nothing | No API key set (tray → Set API key…), or no internet — the app silently falls back to the local transcription. |

## Project structure

```
main.py      entry point
dictation/
  bootstrap.py             UTF-8 stdio, CUDA DLL paths
  config.py                constants + persisted Settings
  audio.py                 microphone discovery + Recorder (voice/silence tracking)
  transcriber.py           faster-whisper wrapper (GPU→CPU fallback, confidence)
  textclean.py             deterministic transcript cleanup (fillers, stutter)
  enhancer.py              Claude cleanup/translation with history context
  history.py               JSONL dictation history (capped at 500)
  hotkey.py                global hotkey strings + listener
  updates.py               GitHub releases update check
  app.py                   Controller + main() wiring
  ui/
    overlay.py             floating waveform pill
    tray.py                tray icon + settings menu
    review_dialog.py       low-confidence transcript confirm/fix
    shortcut_dialog.py     press-to-set shortcut capture
    download_dialog.py     first-run model download
    history_window.py      history viewer
```
