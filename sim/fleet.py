# -*- coding: utf-8 -*-
"""
sim.fleet -- Multi-vehicle fleet management.

Manages cross-vehicle interactions:
  - Relay toggle noise injection (electrical coupling)
  - Power state coordination
  - Fleet-wide statistics
"""
import threading


class SimFleet:
    """Manages multiple simulated vehicles and cross-vehicle effects."""

    def __init__(self):
        self.vehicles = []
        self._lock = threading.Lock()

    def add(self, vehicle):
        """Register a vehicle with the fleet."""
        with self._lock:
            self.vehicles.append(vehicle)
            vehicle.fleet = self

    def notify_relay_toggle(self, source_sysid, amplitude=25.0):
        """
        When a vehicle's relay toggles, inject noise into all other vehicles.

        This simulates electrical coupling through the shared power bus
        in the test fixture.
        """
        with self._lock:
            for v in self.vehicles:
                if v.sysid != source_sysid:
                    v.inject_relay_noise(amplitude)

    @property
    def count(self):
        with self._lock:
            return len(self.vehicles)
