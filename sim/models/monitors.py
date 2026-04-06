# -*- coding: utf-8 -*-
"""
sim.models.monitors -- Contingency management monitor system.

Simulates Pandion's monitor evaluation pipeline:
  1. Conditions are continuously evaluated against vehicle state
  2. Newly triggered monitors enter 'setting' state (latching delay)
  3. After eval_window they latch to 'set' state
  4. Override/clear suppresses a monitor for one evaluation cycle
  5. Overridden monitors don't re-assert from conditions
  6. Safety-critical monitors can abort IBIT
"""
import time
import threading

from ..config.defaults import SAFETY_CRITICAL_MONITOR_IDS, INSStatus, GNSSFix


class MonitorSystem:
    """Thread-safe monitor evaluation and state machine."""

    def __init__(self, eval_window_s=0.6):
        self.eval_window = eval_window_s

        self._set = set()
        self._setting = {}        # mid -> timestamp when it started setting
        self._overridden = set()
        self._suppressed = set()  # cleared monitors skipped for one cycle
        self._lock = threading.Lock()

        # Event tracking
        self._last_event_id = 0
        self._last_event_ts = 0
        self._last_event_flags = 0  # 1=set, 2=cleared

    def evaluate(self, vehicle, conditions_fn):
        """
        Run all monitor conditions against current vehicle state.

        Args:
            vehicle: PandionVehicleSim instance
            conditions_fn: callable(vehicle) -> dict of mid -> (name, eval_fn)
        """
        now = time.time()
        conds = conditions_fn(vehicle)

        with self._lock:
            # Latch: setting -> set after eval_window
            newly_set = []
            for mid, ts in list(self._setting.items()):
                if now - ts >= self.eval_window:
                    self._set.add(mid)
                    newly_set.append(mid)
                    self._last_event_id = mid
                    self._last_event_ts = int(now * 1000) & 0xFFFFFFFF
                    self._last_event_flags = 1  # set event
            for mid in newly_set:
                del self._setting[mid]

            # Evaluate conditions
            for mid, (name, fn) in conds.items():
                if mid in self._overridden or mid in self._suppressed:
                    continue
                try:
                    if fn():
                        if mid not in self._set and mid not in self._setting:
                            self._setting[mid] = now
                except Exception:
                    pass

            # Clear suppression after one cycle
            self._suppressed.clear()

    def clear(self, mid):
        """Clear a monitor (operator override)."""
        with self._lock:
            self._set.discard(mid)
            self._setting.pop(mid, None)
            self._overridden.add(mid)
            self._suppressed.add(mid)
            self._last_event_id = mid
            self._last_event_ts = int(time.time() * 1000) & 0xFFFFFFFF
            self._last_event_flags = 2  # cleared event

    def cancel_override(self, mid):
        """Cancel override — monitor can re-assert from conditions."""
        with self._lock:
            self._overridden.discard(mid)

    def force_set(self, mid):
        """Force a monitor to SET state."""
        with self._lock:
            self._set.add(mid)

    def get_state(self):
        """Return (set, setting, overridden) as frozen sets."""
        with self._lock:
            return set(self._set), set(self._setting.keys()), set(self._overridden)

    def get_event(self):
        """Return (event_id, event_ts, event_flags) for WCA status."""
        with self._lock:
            return self._last_event_id, self._last_event_ts, self._last_event_flags

    def has_safety_critical(self):
        """Check if any safety-critical monitor is SET."""
        with self._lock:
            return bool(self._set & SAFETY_CRITICAL_MONITOR_IDS)

    @property
    def is_clear(self):
        """True if no monitors are set or setting."""
        with self._lock:
            return not self._set and not self._setting

    def reset(self):
        """Full reset."""
        with self._lock:
            self._set.clear()
            self._setting.clear()
            self._overridden.clear()
            self._suppressed.clear()


def default_monitor_conditions(vehicle):
    """
    Standard Pandion monitor condition evaluator.

    Returns dict of monitor_id -> (name, eval_fn).
    eval_fn is a no-arg callable that returns True if the monitor
    condition is active.
    """
    be = vehicle._boot_elapsed

    return {
        0:  ("GNSS Config In Process",
             lambda: not vehicle._booted or be() < 10),
        1:  ("INS Aligning",
             lambda: vehicle._sensors.ins_status < INSStatus.FULL),
        2:  ("Inner Geofence Invalid",
             lambda: False),  # Asserted on boot via boot_monitors list, stays cleared after override
        3:  ("Outer Geofence Invalid",
             lambda: False),  # Same -- real vehicle loads geofence data from MC
        4:  ("Deconfliction Data Invalid",
             lambda: False),  # Same -- real vehicle loads deconfliction from MC
        5:  ("MC Clock Not Synced",
             lambda: not vehicle._booted or be() < 12),
        10: ("RC Rotor Switch Not Set",
             lambda: vehicle.flight_regime == 1),  # appears after ARM
        11: ("VN GPS Error",
             lambda: vehicle._sensors.gnss_fix[0] < GNSSFix.FIX_3D),
        12: ("VN Degraded Nav",
             lambda: vehicle._sensors.ins_status < INSStatus.FULL),
        20: ("GCS Link Lost",
             lambda: vehicle._gcs_link_lost and vehicle._last_gcs_hb > 0),  # Only after first HB received
        30: ("GNSS Quality Degraded",
             lambda: vehicle._sensors.gnss_degraded),
        40: ("BMS Undervoltage",
             lambda: vehicle._bms.pack_voltage < 21000),
    }
