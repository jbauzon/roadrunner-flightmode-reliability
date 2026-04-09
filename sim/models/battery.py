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
    """7S LiPo battery model with non-linear discharge curve."""

    def __init__(self, capacity_mAh=None, cells=None, voltage_per_cell_mV=None):
        self.capacity_mah = capacity_mAh or BMS_CAPACITY_MAH
        self.cells = cells or BMS_CELLS
        self.nom_cell_mv = voltage_per_cell_mV or BMS_VOLTAGE_PER_CELL_MV

        self.remaining = self.capacity_mah
        self.soc = 100.0
        self.pack_voltage = self.cells * self._cell_voltage_from_soc(self.soc)
        self.current_cA = 0
        self.cell_temps = [250] * 4  # centi-Celsius (25.0 C)
        self.state = 1  # operational

    def _cell_voltage_from_soc(self, soc_pct: float) -> float:
        """Non-linear LiPo cell voltage from state of charge (0-100%)."""
        # Piecewise linear approximation of LiPo discharge curve
        if soc_pct > 90:
            # 90-100%: 4.15V - 4.20V
            return 4150 + (soc_pct - 90) * 5  # 4150-4200 mV
        elif soc_pct > 20:
            # 20-90%: 3.60V - 4.15V (flat plateau)
            return 3600 + (soc_pct - 20) * (550 / 70)  # 3600-4150 mV
        elif soc_pct > 5:
            # 5-20%: 3.30V - 3.60V (knee)
            return 3300 + (soc_pct - 5) * (300 / 15)  # 3300-3600 mV
        else:
            # 0-5%: 3.00V - 3.30V (cutoff region)
            return 3000 + soc_pct * (300 / 5)  # 3000-3300 mV

    def step(self, dt, total_servo_current_mA):
        """Update battery state for dt seconds."""
        self.current_cA = int(total_servo_current_mA / 10)

        # Deplete SoC
        draw_mah = total_servo_current_mA * (dt / 3600.0)  # mAh consumed in this tick
        self.soc = max(0.0, self.soc - (draw_mah / self.capacity_mah) * 100)
        self.remaining = self.capacity_mah * self.soc / 100.0

        # Non-linear voltage from SoC + sag + noise
        sag = total_servo_current_mA * 0.002
        noise = random.gauss(0, 50)
        self.pack_voltage = int(
            self.cells * self._cell_voltage_from_soc(self.soc) - sag + noise
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
        self.remaining = self.capacity_mah
        self.soc = 100.0
        self.pack_voltage = self.cells * self._cell_voltage_from_soc(self.soc)
        self.current_cA = 0
        self.cell_temps = [250] * 4
