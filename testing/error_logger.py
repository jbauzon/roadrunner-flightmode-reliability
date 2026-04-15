"""
testing.error_logger -- Cross-session error log for the IBIT test system.

Writes every test error, warning, and anomaly to a persistent JSONL file
(one JSON object per line) that survives across batch runs. Designed for
post-run analysis, trending, and pattern detection.

Log file: <log_directory>/errors/error_log.jsonl

Each entry:
    {
        "timestamp": "2026-04-14T18:23:45.123",
        "level":     "ERROR" | "WARNING" | "INFO",
        "category":  "RELAY" | "CONNECTION" | "IBIT" | "ARM" | "MONITOR" | "STATE" | "SYSTEM",
        "serial":    "RR-SIM-001",
        "iteration": 42,
        "message":   "IBIT timeout after 300s",
        "detail":    {  ...  }          # optional structured context
    }

Usage:
    error_log = ErrorLogger(log_directory)
    error_log.error("IBIT", "RR-SIM-001", 3, "IBIT timeout after 300s")
    error_log.warning("ARM", "RR-SIM-001", 3, "ARM rejected - 4 monitors SET", {"monitors": [0,1,2,3]})
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import Any, Dict, Optional


class ErrorLogger:
    """
    Persistent cross-session error log.

    Thread-safe, append-only, survives process restarts.
    One JSONL entry per event, flushed immediately to disk.
    """

    LEVELS    = ('INFO', 'WARNING', 'ERROR', 'CRITICAL')
    CATEGORIES = (
        'RELAY',        # Relay enable/disable failures
        'CONNECTION',   # MAVLink connection, heartbeat loss
        'IBIT',         # IBIT execution, mistracking, timeout
        'ARM',          # ARM command, monitor management
        'MONITOR',      # Monitor SET/clear operations
        'STATE',        # State capture, restoration, DISARM
        'SYSTEM',       # Software exceptions, unexpected states
    )

    def __init__(self, log_directory: str):
        self._dir  = os.path.join(log_directory, 'errors')
        self._path = os.path.join(self._dir, 'error_log.jsonl')
        self._lock = threading.Lock()
        os.makedirs(self._dir, exist_ok=True)

    # ── Public API ───────────────────────────────────────────────────────

    def info(self, category: str, serial: str, iteration: int,
             message: str, detail: Optional[Dict[str, Any]] = None) -> None:
        """Log an informational event (unexpected but non-critical)."""
        self._write('INFO', category, serial, iteration, message, detail)

    def warning(self, category: str, serial: str, iteration: int,
                message: str, detail: Optional[Dict[str, Any]] = None) -> None:
        """Log a warning event (degraded but recoverable)."""
        self._write('WARNING', category, serial, iteration, message, detail)

    def error(self, category: str, serial: str, iteration: int,
              message: str, detail: Optional[Dict[str, Any]] = None) -> None:
        """Log an error event (test failed or aborted)."""
        self._write('ERROR', category, serial, iteration, message, detail)

    def critical(self, category: str, serial: str, iteration: int,
                 message: str, detail: Optional[Dict[str, Any]] = None) -> None:
        """Log a critical safety event (relay failure, TERMINAL mode, etc.)."""
        self._write('CRITICAL', category, serial, iteration, message, detail)

    def get_recent(self, n: int = 50,
                   level: Optional[str] = None,
                   category: Optional[str] = None,
                   serial: Optional[str] = None) -> list:
        """
        Read the most recent N entries, optionally filtered.

        Args:
            n:        Maximum entries to return
            level:    Filter by level ('ERROR', 'WARNING', etc.)
            category: Filter by category ('RELAY', 'IBIT', etc.)
            serial:   Filter by UUT serial number

        Returns:
            List of entry dicts, most recent last.
        """
        if not os.path.exists(self._path):
            return []
        try:
            with open(self._path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except OSError:
            return []

        entries = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if level and entry.get('level') != level:
                    continue
                if category and entry.get('category') != category:
                    continue
                if serial and entry.get('serial') != serial:
                    continue
                entries.append(entry)
            except json.JSONDecodeError:
                continue

        return entries[-n:]

    def get_summary(self) -> Dict[str, Any]:
        """Return a summary of all logged errors grouped by level and category."""
        if not os.path.exists(self._path):
            return {}
        try:
            with open(self._path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except OSError:
            return {}

        counts: Dict[str, Dict] = {
            'by_level':    {lvl: 0 for lvl in self.LEVELS},
            'by_category': {cat: 0 for cat in self.CATEGORIES},
            'by_serial':   {},
            'total':       0,
        }
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                counts['total'] += 1
                lvl = e.get('level', '')
                cat = e.get('category', '')
                ser = e.get('serial', 'unknown')
                if lvl in counts['by_level']:
                    counts['by_level'][lvl] += 1
                if cat in counts['by_category']:
                    counts['by_category'][cat] += 1
                counts['by_serial'][ser] = counts['by_serial'].get(ser, 0) + 1
            except json.JSONDecodeError:
                continue

        return counts

    # ── Internal ─────────────────────────────────────────────────────────

    def _write(self, level: str, category: str, serial: str,
               iteration: int, message: str,
               detail: Optional[Dict[str, Any]]) -> None:
        """Write one entry to the JSONL file."""
        entry: Dict[str, Any] = {
            'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3],
            'level':     level,
            'category':  category,
            'serial':    serial,
            'iteration': iteration,
            'message':   message,
        }
        if detail:
            entry['detail'] = detail

        line = json.dumps(entry, ensure_ascii=False) + '\n'
        with self._lock:
            try:
                with open(self._path, 'a', encoding='utf-8') as f:
                    f.write(line)
            except OSError:
                pass  # Don't crash the test if logging fails
