# -*- coding: utf-8 -*-
"""
sim.recorder -- Telemetry recording in MAVLink .tlog format.

Records all outgoing MAVLink messages with microsecond timestamps
for offline analysis with MAVExplorer, pymavlink, or any .tlog reader.

Usage:
    recorder = TelemetryRecorder("output.tlog")
    recorder.start()
    recorder.record(raw_bytes)  # call after each mav.send()
    recorder.stop()
"""
from __future__ import annotations

import os
import struct
import time
import threading
from typing import Optional


class TelemetryRecorder:
    """Records MAVLink messages to .tlog binary format."""

    def __init__(self, path: str):
        self.path = path
        self._file = None
        self._lock = threading.Lock()
        self._count = 0
        self._start_time = 0.0

    def start(self) -> None:
        """Open the log file for writing."""
        os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
        self._file = open(self.path, 'wb')
        self._start_time = time.time()
        self._count = 0

    def record(self, raw_bytes: bytes) -> None:
        """Record a raw MAVLink message with timestamp."""
        if not self._file:
            return
        # .tlog format: 8-byte little-endian microsecond timestamp + raw message
        ts_us = int((time.time() - self._start_time) * 1e6)
        with self._lock:
            self._file.write(struct.pack('<Q', ts_us))
            self._file.write(raw_bytes)
            self._count += 1

    def stop(self) -> None:
        """Flush and close the log file."""
        if self._file:
            with self._lock:
                self._file.flush()
                self._file.close()
            self._file = None

    @property
    def message_count(self) -> int:
        return self._count

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()
