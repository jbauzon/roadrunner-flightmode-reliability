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

from ..config.defaults import SAFETY_CRITICAL_MONITOR_IDS, INSStatus, GNSSFix, FlightRegime


class MonitorSystem:
    """Thread-safe monitor evaluation and state machine."""

    def __init__(self, eval_window_s=0.6):
        self.eval_window = eval_window_s

        self._set = set()
        self._setting = {}        # mid -> timestamp when it started setting
        self._overridden = set()
        self._suppressed = set()  # cleared monitors skipped for one cycle
        self._conditions = {}     # mid -> (name, condition_fn)  registered dynamically
        self._lock = threading.Lock()
        self._listeners = []  # list of callables: fn(event_type, monitor_id)

        # Event tracking
        self._last_event_id = 0
        self._last_event_ts = 0
        self._last_event_flags = 0  # 1=set, 2=cleared

    def on_event(self, callback):
        """Register a listener. Called with (event_type, monitor_id).

        Event types: 'set', 'cleared', 'overridden', 'setting'
        """
        self._listeners.append(callback)

    def register_condition(self, monitor_id, condition_fn, name=None):
        """Register a condition function for a monitor.

        Args:
            monitor_id: Integer monitor ID.
            condition_fn: No-arg callable returning True if monitor should be SET.
            name: Optional human-readable name for the condition.
        """
        label = name or f"Monitor {monitor_id}"
        self._conditions[monitor_id] = (label, condition_fn)

    def _emit(self, event_type: str, monitor_id: int):
        """Notify all listeners of a monitor event."""
        for fn in self._listeners:
            try:
                fn(event_type, monitor_id)
            except Exception:
                pass

    def evaluate(self, vehicle, conditions_fn):
        """
        Run all monitor conditions against current vehicle state.

        Evaluates both the conditions returned by conditions_fn and any
        dynamically registered conditions (self._conditions).

        Args:
            vehicle: PandionVehicleSim instance
            conditions_fn: callable(vehicle) -> dict of mid -> (name, eval_fn)
        """
        now = time.time()
        conds = conditions_fn(vehicle)
        # Merge registered conditions (registered conditions take precedence
        # for duplicate IDs since they are more specific)
        merged = dict(conds)
        merged.update(self._conditions)
        events_to_emit = []

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
                    events_to_emit.append(('set', mid))
            for mid in newly_set:
                del self._setting[mid]

            # Evaluate conditions
            for mid, (name, fn) in merged.items():
                if mid in self._overridden or mid in self._suppressed:
                    continue
                try:
                    if fn():
                        if mid not in self._set and mid not in self._setting:
                            self._setting[mid] = now
                            events_to_emit.append(('setting', mid))
                except Exception:
                    pass

            # Clear suppression after one cycle
            self._suppressed.clear()

        # Emit outside lock
        for evt_type, mid in events_to_emit:
            self._emit(evt_type, mid)

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
        self._emit('cleared', mid)

    def cancel_override(self, mid):
        """Cancel override — monitor can re-assert from conditions."""
        with self._lock:
            self._overridden.discard(mid)

    def force_set(self, mid):
        """Force a monitor to SET state."""
        with self._lock:
            self._set.add(mid)
        self._emit('overridden', mid)

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
        """Full reset (preserves registered conditions)."""
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

    Monitor ID ranges:
       0- 9: Boot monitors (set on power-on, cleared by GCS before ARM)
      10-19: Post-ARM monitors (set after ARM, cleared by GCS before test)
      20-29: Runtime monitors (evaluated continuously)
      30-39: Sensor quality monitors
      40-49: Power/BMS monitors
      50-59: Safety-critical monitors (can abort IBIT)
    """
    be = vehicle._boot_elapsed

    return {
        # ── Boot monitors (0-9) ───────────────────────────────────────
        0:  ("INS Not Aligned",
             lambda: vehicle._sensors.ins_status < INSStatus.FULL),
        1:  ("GNSS No Fix",
             lambda: vehicle._sensors.gnss_fix[0] < GNSSFix.FIX_3D),
        2:  ("Actuation Not Initialized",
             lambda: not vehicle._booted),
        3:  ("BMS Not Ready",
             lambda: not vehicle._booted),
        4:  ("Engine Controller Not Ready",
             lambda: not vehicle._booted),
        5:  ("Comms Link Not Established",
             lambda: not vehicle._booted),

        # ── Post-ARM monitors (10-19) ─────────────────────────────────
        10: ("RC Rotor Switch Not Set",
             lambda: vehicle.flight_regime == FlightRegime.ARMED),
        11: ("Landing Gear Deployed",
             lambda: False),  # Only asserted via override when gear is down
        12: ("Nest Connection Lost",
             lambda: (vehicle._active_params.get('USE_NEST', 0) == 1
                      and vehicle.flight_regime == FlightRegime.ARMED)),

        # ── Runtime monitors (20-29) ──────────────────────────────────
        20: ("GCS Link Lost",
             lambda: vehicle._gcs_link_lost and vehicle._last_gcs_hb > 0),
        21: ("Low Battery Voltage",
             lambda: vehicle._bms.pack_voltage < 22000),
        22: ("High Servo Temperature",
             lambda: any(s.temp > 80 for s in vehicle.servos.values())),
        23: ("INS Degraded",
             lambda: vehicle._sensors.ins_status < INSStatus.FULL
                     and vehicle._booted),
        24: ("GNSS Fix Lost During Flight",
             lambda: (vehicle._booted
                      and vehicle.flight_regime == FlightRegime.ARMED
                      and vehicle._sensors.gnss_fix[0] < GNSSFix.FIX_3D)),
        25: ("Engine 1 RPM Low",
             lambda: (vehicle.flight_regime == FlightRegime.ARMED
                      and vehicle._sensors.eng1_mode == 2
                      and vehicle._sensors.eng1_rpm < 30000)),
        26: ("Engine 2 RPM Low",
             lambda: (vehicle.flight_regime == FlightRegime.ARMED
                      and vehicle._sensors.eng2_mode == 2
                      and vehicle._sensors.eng2_rpm < 30000)),
        27: ("Actuation Bus Fault",
             lambda: False),  # Only set via fault injection
        28: ("BMS Cell Imbalance",
             lambda: (max(vehicle._bms.get_cell_voltage())
                      - min(vehicle._bms.get_cell_voltage()) > 500
                      if hasattr(vehicle._bms, 'get_cell_voltage')
                      else False)),
        29: ("Servo Overcurrent",
             lambda: any(s.cur > 5000 for s in vehicle.servos.values())),

        # ── Sensor quality monitors (30-39) ───────────────────────────
        30: ("GNSS Quality Degraded",
             lambda: vehicle._sensors.gnss_degraded),

        # ── Power/BMS monitors (40-49) ────────────────────────────────
        40: ("BMS Undervoltage",
             lambda: vehicle._bms.pack_voltage < 21000),

        # ── Safety-critical monitors (50-59) ──────────────────────────
        50: ("Emergency Stop Commanded",
             lambda: False),  # Only set via override
        51: ("Power Bus Undervoltage",
             lambda: vehicle._bms.pack_voltage < 18000),
        52: ("Thermal Shutdown Imminent",
             lambda: any(s.temp > 95 for s in vehicle.servos.values())),
    }
