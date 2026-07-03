# Kalbukas

Press a hotkey, speak Lithuanian or English, press it again — your words are
transcribed **locally** (OpenAI Whisper via faster-whisper) and pasted into
whatever app has focus. A floating waveform overlay reacts to your voice while
you talk.

Optionally, an **online mode** sends the transcribed text (never the audio)
to Claude for grammar/punctuation cleanup and LT↔EN translation.

## Features

- **F9 to dictate** (configurable shortcut) — works system-wide, pastes into the focused app or copies to clipboard
- **Fully local transcription** — Whisper `large-v3` on your GPU (NVIDIA, automatic) or CPU; in offline mode the network is hard-blocked at the process level
- **Online AI cleanup (optional)** — one Claude API call fixes transcription errors, grammar and diacritics; falls back to the raw transcription on any failure
- **Translation (online)** — LT → EN or EN → LT
- **Dictation history** — last 500 dictations, browsable/copyable from the tray
- **System tray settings** — language, output mode, offline/online, translation, microphone, shortcut, API key

## Requirements

- Windows 10/11 (primary target), Python 3.10+
- A microphone
- ~3 GB disk for the Whisper `large-v3` model
- Optional: NVIDIA GPU (much faster transcription)
- Optional: an [Anthropic API key](https://console.anthropic.com/) for online mode

## Install

```bash
git clone <this repo>
cd local_dictation_ui
python -m venv venv
venv\Scripts\activate
pip install faster-whisper sounddevice numpy pynput pyperclip PyQt5 anthropic

# Optional GPU support (NVIDIA, CUDA 12) — used automatically when present:
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12

# One-time model download (~3 GB, needs internet):
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
| Mode | Offline (network hard-blocked) or Online (AI cleanup via Claude) |
| Translate | LT → EN / EN → LT (online mode only) |
| Microphone | Pick a specific input device (refreshes live) |
| Change shortcut… | Press any key/combo to make it the new dictation hotkey |
| Set API key… | Paste your Anthropic API key for online mode |
| History… | Browse and copy your last 500 dictations |

Settings persist in `settings.json`, history in `history.jsonl` — both next to
the script. **Don't share `settings.json`; it contains your API key.**

## Privacy

- **Offline mode:** nothing ever leaves your machine — the process' socket
  layer is monkeypatched to raise on any network use.
- **Online mode:** only the transcribed *text* is sent to the Anthropic API
  for cleanup/translation. Audio never leaves your machine in either mode.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `No microphone found` at startup | Windows sees no input device. Wake your Bluetooth headset (take it out of the case), or plug in a mic, then restart. |
| Every dictation says "No speech" | The app is bound to a dead device — common when a Bluetooth headset went to sleep *after* startup. Pick the mic explicitly in tray → Microphone, or restart. |
| `GPU load failed … falling back to CPU` | The CUDA wheels aren't installed (see Install) or the GPU is busy. The app still works, just slower. |
| Text pastes garbled diacritics | Make sure the target app accepts Ctrl+V paste; try Output → Clipboard only and paste manually. |
| Online mode does nothing | No API key set (tray → Set API key…), or no internet — the app silently falls back to the raw transcription. |

## Project structure

```
main.py      entry point
dictation/
  bootstrap.py             UTF-8 stdio, offline env vars, CUDA DLL paths
  config.py                constants + persisted Settings
  netlock.py               reversible process-wide network lock
  audio.py                 microphone discovery + Recorder
  transcriber.py           faster-whisper wrapper (GPU→CPU fallback)
  enhancer.py              Claude cleanup/translation (online mode)
  history.py               JSONL dictation history (capped at 500)
  hotkey.py                global hotkey strings + listener
  app.py                   Controller + main() wiring
  ui/
    overlay.py             floating waveform pill
    tray.py                tray icon + settings menu
    shortcut_dialog.py     press-to-set shortcut capture
    history_window.py      history viewer
```
