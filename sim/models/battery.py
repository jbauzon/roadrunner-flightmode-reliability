# -*- coding: utf-8 -*-
"""
sim.models.battery -- Battery Management System (BMS) model.

Simulates a 7S LiPo pack with:
  - Voltage sag under load (proportional to total servo current)
  - Capacity depletion over time
  - Per-cell voltage variation
  - Cell temperature tracking
  - State of charge calculation
  - Undervoltage condition for monitor triggering
"""
import random

from ..config.defaults import BMS_CAPACITY_MAH, BMS_CELLS, BMS_VOLTAGE_PER_CELL_MV


class BatteryModel:
    """7S LiPo battery model with load-dependent voltage sag."""

    def __init__(self, capacity_mAh=None, cells=None, voltage_per_cell_mV=None):
        self.capacity = capacity_mAh or BMS_CAPACITY_MAH
        self.cells = cells or BMS_CELLS
        self.nom_cell_mv = voltage_per_cell_mV or BMS_VOLTAGE_PER_CELL_MV

        self.remaining = self.capacity
        self.pack_voltage = self.cells * self.nom_cell_mv
        self.current_cA = 0
        self.soc = 100
        self.cell_temps = [250] * 4  # centi-Celsius (25.0 C)
        self.state = 1  # operational

    def step(self, dt, total_servo_current_mA):
        """Update battery state for dt seconds."""
        self.current_cA = int(total_servo_current_mA / 10)

        # Deplete capacity
        self.remaining -= total_servo_current_mA * dt / 3600
        self.remaining = max(0, self.remaining)
        self.soc = int(100 * self.remaining / self.capacity)

        # Voltage sag under load
        sag = total_servo_current_mA * 0.002
        self.pack_voltage = int(
            self.cells * self.nom_cell_mv - sag + random.gauss(0, 50)
        )
        self.pack_voltage = max(18000, self.pack_voltage)

        # Cell temperature creep
        for i in range(4):
            delta = (total_servo_current_mA * 0.0001 -
                     (self.cell_temps[i] - 250) * 0.001)
            self.cell_temps[i] += int(delta * dt)

    def get_cell_voltage(self):
        """Return per-cell voltage with variation."""
        base = self.pack_voltage // self.cells
        return [base + random.randint(-30, 30) for _ in range(self.cells)]

    def reset(self):
        """Reset to full charge."""
        self.remaining = self.capacity
        self.pack_voltage = self.cells * self.nom_cell_mv
        self.current_cA = 0
        self.soc = 100
        self.cell_temps = [250] * 4
