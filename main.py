"""Entry point for the dictation app.

Usage:
    python main.py              # normal use (offers a model download if needed)
    python main.py --download   # headless model download, e.g. for scripting
"""

import sys

DOWNLOAD_MODE = "--download" in sys.argv

# bootstrap must run before dictation.app imports faster_whisper — it
# registers the CUDA DLL directories.
from dictation import bootstrap, config  # noqa: E402

bootstrap.apply()
config.migrate_legacy_files()  # before anything reads the model/settings paths

if DOWNLOAD_MODE:
    from dictation import transcriber

    size = transcriber.resolve_model_size(config.Settings.load().model)
    print("Downloading model '%s' (one time)..." % size)
    transcriber.download(size)
    print("Done. Future runs use the local copy.")
else:
    from dictation.app import main

    main()
