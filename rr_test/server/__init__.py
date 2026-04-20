# SPDX-FileCopyrightText: 2026 Anduril Industries, Inc.
# SPDX-License-Identifier: Apache-2.0
"""WebSocket + HTTP backend for the React web GUI.

Split into focused modules:

    app_state.py     AppState — central mutable state + settings persistence
    broadcaster.py   Broadcaster — thread-safe WS push to all clients
    callbacks.py     wire_callbacks() — executor → WS event bridge
    handlers.py      CommandHandler — 14 cmd.* handlers + debug dispatch
    server.py        Bootstrap: ws_handler, HTTP server, main()

Entry points:
    python -m rr_test.server [--sitl]    # canonical
    python ws_server.py [--sitl]         # legacy shim
"""
from __future__ import annotations

from rr_test.server.server import main

__all__ = ["main"]
