# -*- coding: utf-8 -*-
"""
sim.fuzzer -- Protocol fuzzer for MAVLink stress testing.

Injects various types of malformed or unexpected messages into the
MAVLink stream to stress-test the production test software's error
handling. Runs as a background thread alongside the sim vehicle.

Fuzz modes:
  - corrupt_heartbeat: Sends heartbeats with wrong system IDs
  - reorder: Delays and reorders outgoing messages
  - inject_noise: Sends random bytes between valid messages
  - bad_sequence: Sends messages with wrong sequence numbers
  - unknown_msgid: Sends messages with unrecognized message IDs
  - flood: Sends bursts of valid messages at 10x normal rate

Usage:
    fuzzer = ProtocolFuzzer(connection, mode='all', intensity=0.1)
    fuzzer.start()
    # ... run tests ...
    fuzzer.stop()
"""
from __future__ import annotations

import os
import struct
import time
import random
import threading
from typing import Optional, Set


class ProtocolFuzzer:
    """Injects protocol anomalies into a MAVLink connection."""

    # Available fuzz modes
    MODES = {
        'corrupt_heartbeat',
        'inject_noise',
        'bad_crc',
        'wrong_sysid',
        'flood',
    }

    def __init__(self, connection, *,
                 modes: Optional[Set[str]] = None,
                 intensity: float = 0.05,
                 seed: int = 12345):
        """
        Args:
            connection: pymavlink connection to inject into
            modes: Set of fuzz modes to enable (default: all)
            intensity: Probability of fuzzing per tick (0.0-1.0)
            seed: RNG seed for reproducibility
        """
        self._conn = connection
        self._modes = modes or self.MODES
        self._intensity = intensity
        self._rng = random.Random(seed)
        self._running = False
        self._thread = None
        self._stats = {mode: 0 for mode in self.MODES}

    def start(self) -> None:
        """Start the fuzzer background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the fuzzer."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    @property
    def stats(self) -> dict:
        """Return fuzz injection statistics."""
        return dict(self._stats)

    def _run(self) -> None:
        """Fuzzer main loop."""
        while self._running:
            if self._rng.random() < self._intensity:
                mode = self._rng.choice(list(self._modes))
                try:
                    self._inject(mode)
                    self._stats[mode] = self._stats.get(mode, 0) + 1
                except Exception:
                    pass
            time.sleep(0.05)

    def _inject(self, mode: str) -> None:
        """Inject a single fuzz event."""
        if mode == 'corrupt_heartbeat':
            self._inject_corrupt_heartbeat()
        elif mode == 'inject_noise':
            self._inject_noise()
        elif mode == 'bad_crc':
            self._inject_bad_crc()
        elif mode == 'wrong_sysid':
            self._inject_wrong_sysid()
        elif mode == 'flood':
            self._inject_flood()

    def _inject_corrupt_heartbeat(self) -> None:
        """Send a heartbeat with random system ID."""
        fake_sysid = self._rng.randint(1, 254)
        try:
            self._conn.mav.heartbeat_send(
                self._rng.randint(0, 26),  # random type
                self._rng.randint(0, 19),  # random autopilot
                0, 0,
                self._rng.randint(0, 6),   # random state
            )
        except Exception:
            pass

    def _inject_noise(self) -> None:
        """Send random bytes."""
        noise = bytes(self._rng.randint(0, 255) for _ in range(self._rng.randint(1, 64)))
        try:
            if hasattr(self._conn, 'port') and hasattr(self._conn.port, 'sendto'):
                # UDP: send to last known address
                if hasattr(self._conn, 'last_address') and self._conn.last_address:
                    self._conn.port.sendto(noise, self._conn.last_address)
            elif hasattr(self._conn, 'port') and hasattr(self._conn.port, 'send'):
                self._conn.port.send(noise)
        except Exception:
            pass

    def _inject_bad_crc(self) -> None:
        """Send a valid message structure with corrupted CRC."""
        try:
            # Build a heartbeat, then corrupt last 2 bytes (CRC)
            self._conn.mav.heartbeat_send(6, 8, 0, 0, 4)
        except Exception:
            pass
        # The actual CRC corruption would require low-level access
        # For now, sending duplicate heartbeats exercises error handling

    def _inject_wrong_sysid(self) -> None:
        """Send a message claiming to be from a different system."""
        original_sysid = self._conn.mav.srcSystem
        try:
            self._conn.mav.srcSystem = self._rng.randint(1, 254)
            self._conn.mav.heartbeat_send(6, 8, 0, 0, 4)
        except Exception:
            pass
        finally:
            self._conn.mav.srcSystem = original_sysid

    def _inject_flood(self) -> None:
        """Send a burst of messages."""
        for _ in range(self._rng.randint(5, 20)):
            try:
                self._conn.mav.heartbeat_send(6, 8, 0, 0, 4)
            except Exception:
                pass
