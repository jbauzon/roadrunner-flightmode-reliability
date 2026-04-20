"""
ws_server.py — WebSocket bridge between the React frontend and the Python backend.

This is a thin wrapper that:
  1. Runs an asyncio WebSocket server on port 18889
  2. Translates ExecutorCallbacks events into JSON messages (server → client)
  3. Translates JSON commands from the frontend into calls on existing code (client → server)

All domain logic remains in vehicle/, testing/, hardware/, sim/ — untouched.

Usage:
    python ws_server.py              # Start backend + WebSocket server
    python ws_server.py --sitl       # Auto-launch SITL on startup
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import threading
import argparse
from datetime import datetime
from typing import Any, Optional, Set

import websockets
from websockets.asyncio.server import serve, ServerConnection
from websockets.http11 import Response

# ---------------------------------------------------------------------------
# Project root = two levels up from this file (rr_test/server/server.py -> ..)
# Used for web/dist serving, default log_directory, and CSV profiles path.
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# SITL mode: set env var BEFORE importing rr_test.execution.* so
# connect_to_vehicle allows loopback and uses udpout. This is how we
# launch SITL without runtime monkey-patching.
if "--sitl" in sys.argv:
    os.environ["RR_SITL_MODE"] = "1"

from rr_test.vehicle.connection import UUT
from rr_test.vehicle.constants import TestMode, UUTStatus, AlertSeverity
from rr_test.hardware.daq import SimpleDAQController
from rr_test.execution import UUTTestExecutor, PlaybackTestExecutor
from rr_test.execution.callbacks import ExecutorCallbacks

_log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

WS_PORT = 18889
HTTP_PORT = 18890  # Static file server for the built React frontend

# ── Static file MIME types ────────────────────────────────────────────────────
_MIME_TYPES = {
    ".html": "text/html",
    ".css":  "text/css",
    ".js":   "application/javascript",
    ".json": "application/json",
    ".png":  "image/png",
    ".svg":  "image/svg+xml",
    ".ico":  "image/x-icon",
    ".woff": "font/woff",
    ".woff2":"font/woff2",
    ".ttf":  "font/ttf",
    ".map":  "application/json",
}

_DIST_DIR = os.path.join(_HERE, "web", "dist")


# ═══════════════════════════════════════════════════════════════════════════════
# Application state (mirrors what main_window.py tracks)
# ═══════════════════════════════════════════════════════════════════════════════


# ── Split modules ────────────────────────────────────────────────────
from rr_test.server.app_state import AppState  # noqa: E402
from rr_test.server.broadcaster import Broadcaster  # noqa: E402
from rr_test.server.handlers import CommandHandler  # noqa: E402

async def ws_handler(
    ws: ServerConnection,
    state: AppState,
    broadcaster: Broadcaster,
    cmd_handler: CommandHandler,
) -> None:
    """Handle a single WebSocket client connection."""
    broadcaster.register(ws)
    remote = ws.remote_address
    _log.info("Client connected: %s", remote)

    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await broadcaster.send_to(ws, "error", {"message": "Invalid JSON"})
                continue

            try:
                await cmd_handler.handle(ws, msg)
            except Exception as e:
                _log.exception("Command handler error")
                await broadcaster.send_to(ws, "error", {"message": str(e)})
    except websockets.ConnectionClosed:
        pass
    finally:
        broadcaster.unregister(ws)
        _log.info("Client disconnected: %s", remote)


async def main(auto_sitl: bool | None = None) -> None:
    """Run the WebSocket + HTTP server.

    ``auto_sitl`` overrides detection.  If ``None`` (default), we detect
    ``--sitl`` in ``sys.argv`` so that the ``ws_server.py`` shim and
    ``python -m rr_test.server --sitl`` both work without explicit args.
    """
    if auto_sitl is None:
        auto_sitl = "--sitl" in sys.argv or "-s" in sys.argv
    loop = asyncio.get_running_loop()
    state = AppState()
    broadcaster = Broadcaster(loop)
    cmd_handler = CommandHandler(state, broadcaster)

    _log.info("Starting WebSocket server on ws://0.0.0.0:%d", WS_PORT)

    # ── Static file HTTP server ───────────────────────────────────────────
    has_dist = os.path.isdir(_DIST_DIR) and os.path.isfile(os.path.join(_DIST_DIR, "index.html"))

    async def _http_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Minimal HTTP/1.1 static file server for the built React app."""
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            if not request_line:
                writer.close()
                return

            parts = request_line.decode("utf-8", errors="replace").strip().split()
            method = parts[0] if len(parts) >= 1 else "GET"
            path = parts[1] if len(parts) >= 2 else "/"

            # Consume remaining headers
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=5.0)
                if line in (b"\r\n", b"\n", b""):
                    break

            if method != "GET":
                body = b"Method Not Allowed"
                writer.write(b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: %d\r\n\r\n" % len(body))
                writer.write(body)
                await writer.drain()
                writer.close()
                return

            # Strip query string
            path = path.split("?")[0]

            # Map URL to file
            if path == "/":
                path = "/index.html"

            file_path = os.path.normpath(os.path.join(_DIST_DIR, path.lstrip("/")))

            # Security: prevent directory traversal
            if not file_path.startswith(os.path.normpath(_DIST_DIR)):
                file_path = os.path.join(_DIST_DIR, "index.html")

            # If file doesn't exist, serve index.html (SPA routing)
            if not os.path.isfile(file_path):
                file_path = os.path.join(_DIST_DIR, "index.html")

            ext = os.path.splitext(file_path)[1].lower()
            content_type = _MIME_TYPES.get(ext, "application/octet-stream")

            with open(file_path, "rb") as f:
                body = f.read()

            # Cache hashed assets (js/css) long-term; don't cache index.html
            is_asset = "/assets/" in file_path.replace("\\", "/")
            cache = "public, max-age=31536000, immutable" if is_asset else "no-cache"

            header = (
                f"HTTP/1.1 200 OK\r\n"
                f"Content-Type: {content_type}\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Cache-Control: {cache}\r\n"
                f"Access-Control-Allow-Origin: *\r\n"
                f"\r\n"
            )
            writer.write(header.encode())
            writer.write(body)
            await writer.drain()

        except Exception:
            try:
                writer.write(b"HTTP/1.1 500 Internal Server Error\r\n\r\n")
                await writer.drain()
            except Exception:
                pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    http_server = None
    if has_dist:
        try:
            http_server = await asyncio.start_server(
                _http_handler, "0.0.0.0", HTTP_PORT,
                reuse_address=True,
            )
            _log.info("HTTP server ready on http://0.0.0.0:%d (serving web/dist/)", HTTP_PORT)
        except OSError as e:
            _log.warning(
                "Could not start HTTP server on port %d: %s — "
                "is another instance already running? Use dev mode: npx vite",
                HTTP_PORT, e,
            )
            http_server = None
    else:
        _log.warning("web/dist/ not found — run 'npx vite build' in web/ first. "
                      "HTTP file server disabled; use 'npx vite' for dev mode.")

    async with serve(
        lambda ws: ws_handler(ws, state, broadcaster, cmd_handler),
        "0.0.0.0",
        WS_PORT,
        reuse_address=True,
        # Raise the default 1 MiB message limit so large flight profile
        # CSV uploads (NominalFlight_noRudder.csv is 2.8 MB) fit in a
        # single frame. 64 MiB cap matches the frontend's 50 MB upload
        # limit with headroom for JSON overhead and base64 wrapping.
        max_size=64 * 1024 * 1024,
    ):
        _log.info("WebSocket server ready on ws://0.0.0.0:%d", WS_PORT)

        if has_dist:
            _log.info("Open http://localhost:%d in your browser", HTTP_PORT)
        else:
            _log.info("Run 'npx vite' in web/ and open http://localhost:5173")

        if auto_sitl:
            _log.info("Auto-launching SITL...")
            await cmd_handler._launch_sitl(None, {})  # type: ignore[arg-type]

        # Periodic batch status updates (elapsed/remaining timer)
        async def _batch_ticker() -> None:
            while True:
                await asyncio.sleep(1.0)
                if state.testing_active and state.batch_end_time:
                    now = time.monotonic()
                    elapsed = now - getattr(state, "_batch_start_mono", now)
                    remaining = max(0, state.batch_end_time - now)
                    broadcaster.broadcast("batch.status", {
                        "active": True,
                        "mode": state.test_mode,
                        "current_uut_index": state.current_uut_index,
                        "current_uut_serial": (
                            state.uuts[state.current_uut_index].serial_number
                            if 0 <= state.current_uut_index < len(state.uuts)
                            else None
                        ),
                        "elapsed_seconds": elapsed,
                        "remaining_seconds": remaining,
                        "total_uuts": len(state.uuts),
                        "active_uuts": sum(
                            1 for u in state.uuts
                            if getattr(u, 'status', '') != 'Failed (3x)'
                        ),
                    })

        asyncio.create_task(_batch_ticker())

        try:
            await asyncio.Future()  # run forever
        finally:
            # Server is shutting down — save settings so UUT list persists
            _log.info("Saving settings before shutdown...")
            state.save_settings()
            _log.info("Settings saved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Roadrunner Flight Test — WebSocket backend")
    parser.add_argument("--sitl", action="store_true", help="Auto-launch SITL on startup")
    parser.add_argument("--open", action="store_true", help="Auto-open browser on startup")
    args = parser.parse_args()

    if args.open:
        import webbrowser
        def _open_browser() -> None:
            import time as _t
            _t.sleep(3)
            url = f"http://localhost:{HTTP_PORT}"
            _log.info("Opening %s", url)
            webbrowser.open(url)
        threading.Thread(target=_open_browser, daemon=True).start()

    try:
        asyncio.run(main(auto_sitl=args.sitl))
    except KeyboardInterrupt:
        _log.info("Shutting down")
