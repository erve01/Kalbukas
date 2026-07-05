"""Reversible process-wide network lock.

Offline mode monkeypatches the socket layer so nothing in the process can
touch the network; online mode restores the real functions. Whisper stays
local either way — the HF offline env vars are set in bootstrap and never
lifted.
"""

import socket

_REAL = (socket.socket, socket.create_connection, socket.getaddrinfo)


def _blocked(*_args, **_kwargs):
    raise RuntimeError("Network is blocked (offline mode).")


def apply(mode: str) -> None:
    if mode == "offline":
        socket.socket = socket.create_connection = socket.getaddrinfo = _blocked
    else:
        socket.socket, socket.create_connection, socket.getaddrinfo = _REAL
