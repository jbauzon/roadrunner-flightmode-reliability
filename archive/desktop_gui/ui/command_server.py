from __future__ import annotations

"""
Command Server — TCP remote control interface for the test GUI.

Accepts JSON commands on localhost:18888, dispatches them to the GUI
thread via a pyqtSignal, and returns JSON responses.

Used by: click_start.py, test scripts, CI automation.
"""
import json
import socket
import threading
from typing import Any, Callable, Dict, Optional

from PyQt5.QtCore import QObject, pyqtSignal


class CommandServer(QObject):
    """
    TCP command server for remote GUI control.

    Runs a listener thread on 127.0.0.1:<port>.  Incoming JSON commands
    are dispatched to the GUI thread via ``command_received`` signal.

    Protocol:
        Request:  {"cmd": "<name>", "args": {…}}
        Response: {"ok": true, …} or {"error": "…"}
    """

    command_received = pyqtSignal(str, dict)  # (cmd, args)

    DEFAULT_PORT = 18888

    def __init__(self, port: Optional[int] = None, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self.port = port or self.DEFAULT_PORT
        self._response = {}
        self._event = threading.Event()
        self._server_thread = None

        # Wire signal to internal dispatcher
        self.command_received.connect(self._noop_handler)

    # ── Public API ──────────────────────────────────────────────────────

    def start(self, handler: Callable[[str, dict], dict]) -> None:
        """
        Start the server.

        Args:
            handler: callable(cmd: str, args: dict) -> dict
                     Executed on the GUI thread.  Must return a dict
                     that will be JSON-serialised and sent back to the
                     client.
        """
        # Disconnect noop, connect real handler
        self.command_received.disconnect(self._noop_handler)
        self._handler = handler
        self.command_received.connect(self._dispatch)

        self._server_thread = threading.Thread(
            target=self._listen, daemon=True
        )
        self._server_thread.start()

    def set_response(self, response: dict) -> None:
        """Called by the handler to provide the response."""
        self._response = response
        self._event.set()

    # ── Internals ───────────────────────────────────────────────────────

    def _noop_handler(self, cmd: str, args: dict) -> None:
        """Placeholder until start() wires the real handler."""
        pass

    def _dispatch(self, cmd: str, args: dict) -> None:
        """Runs on GUI thread — calls the handler and stores the response."""
        try:
            result = self._handler(cmd, args)
            self._response = result if isinstance(result, dict) else {'ok': True}
        except Exception as e:
            self._response = {'error': str(e)}
        finally:
            self._event.set()

    def _listen(self) -> None:
        """TCP listener loop (runs in daemon thread)."""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(('127.0.0.1', self.port))
            srv.listen(1)
            srv.settimeout(1.0)
        except OSError as e:
            # Can't log via signal here (thread); print to stderr
            import sys
            print(f"Command server failed to start: {e}", file=sys.stderr)
            return

        while True:
            try:
                conn, _ = srv.accept()
                data = conn.recv(4096).decode('utf-8')
                if data:
                    try:
                        req = json.loads(data)
                        cmd = req.get('cmd', '')
                        args = req.get('args', {})

                        self._event.clear()
                        self._response = {}
                        self.command_received.emit(cmd, args)

                        # Wait for GUI thread to process
                        self._event.wait(timeout=30.0)
                        response = self._response
                    except json.JSONDecodeError:
                        response = {'error': 'Invalid JSON'}

                    conn.sendall(json.dumps(response).encode('utf-8'))
                conn.close()
            except socket.timeout:
                continue
            except Exception:
                break
