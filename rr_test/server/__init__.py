# SPDX-FileCopyrightText: 2026 Anduril Industries, Inc.
# SPDX-License-Identifier: Apache-2.0
"""WebSocket + HTTP backend for the React web GUI.

The entry point is :func:`rr_test.server.server.main` — launched either
via ``python -m rr_test.server`` (canonical) or via the
``ws_server.py`` shim at the project root (legacy, used by ``start.bat``).
"""
from __future__ import annotations

from rr_test.server.server import main

__all__ = ["main"]
