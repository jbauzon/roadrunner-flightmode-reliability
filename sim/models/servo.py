# -*- coding: utf-8 -*-
"""
sim.models.servo -- Servo actuator dynamics model.

Firmware-accurate mistracking detection (from actuation.c):
  - Elevon/Rudder: INSTANT detect when |cmd - fb| > 500 cdeg
  - TVC: consecutive cycle counter -- 5 cycles (50ms) above 500 cdeg threshold

Models:
  - First-order lag tracking with rate limiting and deadband
  - Correlated noise: vibration (low-freq sinusoid), thermal, load-dependent
  - Temperature model with hysteresis (rises faster than falls)
  - Thermal protection shutdown at configurable threshold
  - Intermittent fault injection
  - Mechanical trim offset at boot
  - External noise injection (cross-vehicle relay coupling)
  - Surface coupling (aerodynamic load from other surfaces)
"""
import math
import random

from ..config.defaults import (
    SERVO_TAU, SERVO_MAX_SLEW_CDEG_S, SERVO_DEADBAND_CDEG,
    SERVO_MISTRACK_THRESH_CDEG, SERVO_TVC_CONSEC_MISTRACK_CYCLES,
    SERVO_THERMAL_SHUTDOWN, SERVO_THERMAL_RESTART,
)


class Servo:
    """Single servo actuator with full dynamics model."""

    def __init__(self, name='', tau=None, is_tvc=False):
        self.name = name
        self.is_tvc = is_tvc  # TVC uses cycle counter; elevon/rudder is instant
        self.cmd = 0.0
        self.fb = 0.0
        self.vel = 0.0
        self.cur = 200.0
        self.temp = 25.0
        self.tau = tau or SERVO_TAU

        # Fault states
        self._frozen = False
        self._thermal_shutdown = False
        self._intermittent = False
        self._intermittent_prob = 0.0

        # Mistracking detection (firmware-accurate)
        self._mistrack_cycle_count = 0
        self._mistracking = False

        # Noise state
        self._vib_phase = random.uniform(0, 2 * math.pi)
        self._vib_freq = random.uniform(3.0, 8.0)
        self._ext_noise = 0.0
        self._ext_decay = 0.95

        # Mechanical offset at boot
        self._trim_offset = random.gauss(0, 3.0)
        self.fb = self._trim_offset

    def step(self, dt, global_time, coupling_load=0.0):
        """Advance servo model by dt seconds."""
        self._ext_noise *= self._ext_decay

        # ── Thermal protection ────────────────────────────────────────
        if self.temp >= SERVO_THERMAL_SHUTDOWN:
            self._thermal_shutdown = True
        elif self.temp < SERVO_THERMAL_RESTART:
            self._thermal_shutdown = False

        if self._thermal_shutdown:
            self.cur = 50.0 + random.gauss(0, 5)
            self.temp -= 0.5 * dt
            self._mistracking = True
            return

        # ── Intermittent fault ────────────────────────────────────────
        if self._intermittent and not self._frozen:
            if random.random() < self._intermittent_prob * dt:
                self._frozen = True
            elif self._frozen and random.random() < 0.1 * dt:
                self._frozen = False

        # ── Dynamics ──────────────────────────────────────────────────
        if self._frozen:
            drift = 200.0 + 20.0 * math.sin(global_time * 2.0)
            self.fb = self.cmd + drift
            self.cur = 1500 + random.gauss(0, 80)
        else:
            err = self.cmd - self.fb

            # Deadband
            if abs(err) < SERVO_DEADBAND_CDEG:
                err = 0.0

            # First-order lag with rate limiting
            old_fb = self.fb
            desired = self.fb + (err / self.tau) * dt
            delta = desired - self.fb
            max_delta = SERVO_MAX_SLEW_CDEG_S * dt
            if abs(delta) > max_delta:
                delta = max_delta if delta > 0 else -max_delta
            self.fb += delta
            self.vel = (self.fb - old_fb) / max(dt, 0.001)

            # ── Correlated noise ──────────────────────────────────────
            noise = random.gauss(0, 1.0)
            self._vib_phase += self._vib_freq * dt * 2 * math.pi
            noise += 3.0 * math.sin(self._vib_phase)
            noise += abs(self.vel) * 0.003 * random.gauss(0, 1)
            noise *= (1.0 + max(0, self.temp - 30) * 0.02)
            noise += self._ext_noise * random.gauss(0, 1)

            self.fb += noise * dt

            # Current: effort + velocity + coupling
            self.cur = (abs(err) * 2.5 + abs(self.vel) * 0.5 +
                        coupling_load * 0.3 + random.gauss(200, 15))

        # ── Temperature hysteresis ────────────────────────────────────
        target_temp = 25.0 + abs(self.cmd) * 0.015 + abs(self.cur - 200) * 0.002
        if target_temp > self.temp:
            self.temp += (target_temp - self.temp) * 0.03 * dt
        else:
            self.temp += (target_temp - self.temp) * 0.01 * dt
        self.temp = max(15.0, min(85.0, self.temp))

        # ── Mistracking detection (firmware-accurate) ─────────────────
        # From actuation.c perform_monitoring():
        #   Elevon/rudder: instant -- fabsf(cmd - fb) > 500
        #   TVC: consecutive cycle counter -- 5 cycles above threshold
        track_err = abs(self.cmd - self.fb)

        if self.is_tvc:
            # TVC: consecutive cycle counter (actuation.c:1161-1182)
            if track_err > SERVO_MISTRACK_THRESH_CDEG:
                self._mistrack_cycle_count += 1
                if self._mistrack_cycle_count > SERVO_TVC_CONSEC_MISTRACK_CYCLES:
                    self._mistracking = True
            else:
                self._mistrack_cycle_count = 0
                # Note: firmware clears the monitor when tracking resumes
                # monitor_update(mon, false) -- but we keep _mistracking
                # latched for the IBIT result check
        else:
            # Elevon/rudder: instant (actuation.c:714-721)
            if track_err > SERVO_MISTRACK_THRESH_CDEG:
                self._mistracking = True

    # ── Control ───────────────────────────────────────────────────────

    def freeze(self):
        self._frozen = True

    def unfreeze(self):
        self._frozen = False
        self._mistracking = False
        self._mistrack_cycle_count = 0
        self._thermal_shutdown = False

    def inject_noise(self, amplitude):
        self._ext_noise = amplitude

    def set_intermittent(self, prob):
        self._intermittent = prob > 0
        self._intermittent_prob = prob

    @property
    def is_mistracking(self):
        return self._mistracking

    def reset(self):
        """Full reset to boot state."""
        self.cmd = 0.0
        self.fb = self._trim_offset
        self.vel = 0.0
        self.cur = 200.0
        self.temp = 25.0
        self.unfreeze()
