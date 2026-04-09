"""
testing.callbacks -- Callback protocols for test execution.

Defines the callback interfaces that testing/ and vehicle/ layers use
to communicate with the UI layer (or any consumer). This decouples
the test logic from PyQt5 — the UI provides Qt-bridging adapters,
while non-Qt consumers (CLI tools, test harnesses) can use plain
function callbacks.
"""
from __future__ import annotations
from typing import Callable, Optional, Dict, Any, Protocol


class ExecutorCallbacks:
    """Callback bundle for test executor → UI communication.

    All callbacks are optional (default to no-op).
    The UI layer creates an instance with Qt signal emitters wired in.
    Non-Qt consumers can pass plain functions.
    """

    def __init__(self):
        self.on_progress: Callable[[int], None] = lambda v: None
        self.on_iteration: Callable[[int], None] = lambda v: None
        self.on_status: Callable[[str], None] = lambda s: None
        self.on_complete: Callable[[bool, str], None] = lambda ok, msg: None
        self.on_log: Callable[[str], None] = lambda msg: None
        self.on_time_expired: Callable[[], None] = lambda: None
        self.on_statistics: Callable[[Any], None] = lambda s: None
        self.on_ibit_state: Callable[[str], None] = lambda s: None
        self.on_connection_health: Callable[[bool], None] = lambda h: None
        self.on_alert: Callable[[str], None] = lambda msg: None
        self.on_log_file_size: Callable[[float], None] = lambda mb: None
        self.on_test_duration: Callable[[float], None] = lambda s: None
        self.on_armed_state: Callable[[bool, int], None] = lambda armed, regime: None
        self.on_mode: Callable[[int], None] = lambda mode: None
        self.on_actuator_feedback: Callable[[dict], None] = lambda d: None


class PreparationCallbacks:
    """Callback bundle for preparation → UI communication."""

    def __init__(self):
        self.on_log: Callable[[str], None] = lambda msg: None
        self.on_progress: Callable[[str], None] = lambda s: None
        self.on_armed_state: Callable[[bool, int], None] = lambda armed, regime: None
        self.on_mode: Callable[[int], None] = lambda mode: None
        self.on_connection_health: Callable[[bool], None] = lambda h: None
        self.on_actuator_feedback: Callable[[dict], None] = lambda d: None
