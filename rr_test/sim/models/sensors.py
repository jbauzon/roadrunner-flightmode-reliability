# -*- coding: utf-8 -*-
"""
sim.models.sensors -- INS, GNSS, and engine state models.

Simulates sensor subsystem progression during boot:
  INS:  OFF -> ALIGNING -> DEGRADED -> FULL
  GNSS: NO_FIX -> 2D -> 3D (both receivers)
  Engine: idle state, RPM, EGT

Also handles GNSS degradation injection during IBIT.
"""
import random
import time

from ..config.defaults import INSStatus, GNSSFix


class SensorSuite:
    """Combined INS + GNSS + Engine sensor state."""

    def __init__(self):
        self.ins_status = INSStatus.OFF
        self.gnss_fix = [GNSSFix.NO_FIX, GNSSFix.NO_FIX]
        self.gnss_sats = [0, 0]
        self.gnss_degraded = False

        # Engine
        self.eng1_rpm = 0
        self.eng1_egt = 25
        self.eng1_mode = 0
        self.eng2_rpm = 0
        self.eng2_egt = 25
        self.eng2_mode = 0
        self.fuel_pump_current_mA = 0
        self.fuel_consumed_l = 0.0

        # Engine spool-up state
        self._engine_starting = False

    def update_boot_progression(self, boot_fraction):
        """
        Update sensor state based on boot progress (0.0 to 1.0).

        Called periodically during boot sequence.
        """
        # INS progression
        if boot_fraction < 0.3:
            self.ins_status = INSStatus.ALIGNING
        elif boot_fraction < 0.6:
            self.ins_status = INSStatus.DEGRADED
        else:
            self.ins_status = INSStatus.FULL

        # GNSS progression
        if boot_fraction < 0.2:
            self.gnss_fix = [GNSSFix.NO_FIX, GNSSFix.NO_FIX]
            self.gnss_sats = [0, 0]
        elif boot_fraction < 0.4:
            self.gnss_fix = [GNSSFix.FIX_2D, GNSSFix.NO_FIX]
            self.gnss_sats = [4, 0]
        elif boot_fraction < 0.7:
            self.gnss_fix = [GNSSFix.FIX_3D, GNSSFix.FIX_2D]
            self.gnss_sats = [8, 4]
        else:
            self.gnss_fix = [GNSSFix.FIX_3D, GNSSFix.FIX_3D]
            self.gnss_sats = [12, 10]

    def finalize_boot(self):
        """Set all sensors to fully operational state."""
        self.ins_status = INSStatus.FULL
        self.gnss_fix = [GNSSFix.FIX_3D, GNSSFix.FIX_3D]
        self.gnss_sats = [12, 10]
        self.gnss_degraded = False

        # Engine spool-up (gradual instead of instant)
        self.eng1_mode = 1  # Starting
        self.eng2_mode = 1
        self._engine_starting = True
        import threading
        threading.Thread(target=self._engine_spool_up, daemon=True).start()

    def _engine_spool_up(self):
        """Simulate engine spool-up over ~3 seconds."""
        target_rpm = 45000
        for step in range(30):  # 30 steps over 3 seconds
            if not self._engine_starting:
                break
            progress = (step + 1) / 30.0
            self.eng1_rpm = int(target_rpm * progress + random.randint(-200, 200))
            self.eng2_rpm = int(target_rpm * progress + random.randint(-200, 200))
            self.eng1_egt = int(25 + (450 - 25) * progress + random.randint(-10, 10))
            self.eng2_egt = int(25 + (450 - 25) * progress + random.randint(-10, 10))
            self.fuel_pump_current_mA = int(350 * progress + random.randint(-10, 10))
            time.sleep(0.1)
        self.eng1_mode = 2  # Running
        self.eng2_mode = 2
        self._engine_starting = False

    def degrade_gnss(self):
        """Inject GNSS degradation (for IBIT fault injection)."""
        self.gnss_degraded = True
        self.gnss_fix = [GNSSFix.FIX_2D, GNSSFix.NO_FIX]
        self.gnss_sats = [3, 0]

    def restore_gnss(self):
        """Restore GNSS after degradation."""
        self.gnss_degraded = False
        self.gnss_fix = [GNSSFix.FIX_3D, GNSSFix.FIX_3D]
        self.gnss_sats = [12, 10]

    def update_running(self, dt: float):
        """Update engine telemetry with realistic noise."""
        if self.eng1_rpm > 0:
            self.eng1_rpm = max(0, self.eng1_rpm + random.gauss(0, 100))
            self.eng2_rpm = max(0, self.eng2_rpm + random.gauss(0, 100))
            self.eng1_egt = max(25, self.eng1_egt + random.gauss(0, 2))
            self.eng2_egt = max(25, self.eng2_egt + random.gauss(0, 2))
            # Accumulate fuel consumption (~0.5 L/min per engine at cruise)
            self.fuel_consumed_l += (0.5 / 60.0) * dt

    def reset(self):
        """Full reset to power-off state."""
        self.ins_status = INSStatus.OFF
        self.gnss_fix = [GNSSFix.NO_FIX, GNSSFix.NO_FIX]
        self.gnss_sats = [0, 0]
        self.gnss_degraded = False
        self._engine_starting = False
        self.eng1_rpm = 0
        self.eng1_egt = 25
        self.eng1_mode = 0
        self.eng2_rpm = 0
        self.eng2_egt = 25
        self.eng2_mode = 0
        self.fuel_pump_current_mA = 0
        self.fuel_consumed_l = 0.0
