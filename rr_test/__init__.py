# SPDX-FileCopyrightText: 2026 Anduril Industries, Inc.
# SPDX-License-Identifier: Apache-2.0
"""rr_test — Roadrunner flight controller reliability test system.

Subpackages:
    vehicle    — MAVLink connection, constants, preparation (ARM/DISARM/modes)
    sim        — Software-In-The-Loop vehicle simulator (Pandion dialect 102)
    hardware   — NI-DAQmx relay controller
    execution  — Test executors + callbacks + recovery + telemetry logging
    server     — WebSocket + HTTP backend for the React web GUI
"""
from __future__ import annotations

from rr_test.version import __version__

__all__ = ["__version__"]
