# -*- coding: utf-8 -*-
"""
sim.vehicle -- PandionVehicleSim orchestrator.

This is the top-level vehicle class. It delegates all domain logic to
sub-modules:

  models/servo.py      Servo dynamics, mistracking, thermal protection
  models/battery.py    BMS model with voltage sag
  models/monitors.py   Monitor condition evaluation + latching
  models/sensors.py    INS/GNSS/Engine sensor progression
  telemetry.py         MAVLink TX message encoding
  fleet.py             Cross-vehicle interactions
  config/defaults.py   All constants, enums, tuning params
  config/scenarios.py  Pre-built fault profiles

The orchestrator's responsibilities:
  - Lifecycle (start, stop, power_on, power_off)
  - Thread management (telem loop, monitor eval, sensor loop, RX loop)
  - State machine transitions (ARM/DISARM, mode requests)
  - IBIT sequencing
  - Connecting sub-modules together
"""

import os
import sys
import time
import math
import random
import threading
from typing import Optional

# ── Path setup for dialect loading ────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
_DIAL = os.path.join(_ROOT, "vehicle", "dialects")
if _DIAL not in sys.path:
    sys.path.insert(0, _DIAL)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import importlib
_d = importlib.import_module("pandion_vehicle_roadrunner")
sys.modules["pymavlink.dialects.v10.pandion_vehicle_roadrunner"] = _d
import pymavlink.dialects.v10 as _v10
setattr(_v10, "pandion_vehicle_roadrunner", _d)
from pymavlink import mavutil

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ── Sim sub-modules ──────────────────────────────────────────────────────────
from .config.defaults import (
    FlightRegime, ActuationState, IBITSubstate, MistrackingFlags,
    SURFACE_NAMES, IBIT_PHASE_DURATIONS, IBIT_NEST_COEFFS, SERVO_HARD_LIMITS,
    ARM_FORCE_MAGIC, REBOOT_REQUIRED_PARAMS, DEFAULT_PARAMS,
    RATE_HEARTBEAT, RATE_PANDION_STATUS, RATE_ACTUATION,
    RATE_MONITORS, RATE_ENGINE, RATE_BMS, RATE_WCA, RATE_PDU,
    RATE_HW_SELECTOR,
    MONITOR_OVERRIDE_CANCEL, MONITOR_OVERRIDE_SUPPRESS, MONITOR_OVERRIDE_FORCE_FAULT,
    MAV_TYPE_VTOL_DUOROTOR,
)
from version import __version__
from .models.servo import Servo
from .models.battery import BatteryModel
from .models.monitors import MonitorSystem, default_monitor_conditions
from .models.sensors import SensorSuite
from .telemetry import TelemetryManager
from .clock import SimClock
from .recorder import TelemetryRecorder


def _log(sysid, msg):
    print(f"[SIM:{sysid}] {msg}")


class PandionVehicleSim:
    """
    Production-fidelity Pandion vehicle simulator.

    Single udpout connection for all TX/RX. Zero production code changes.
    """

    def __init__(self, *, vehicle_port, sysid=1,
                 ibit_pass=True, mistracking_flags=0,
                 boot_monitors=None, post_arm_monitors=None,
                 transient_monitor_chance=0.1,
                 ibit_duration_scale=1.0, ibit_cycles=1,
                 boot_time_s=3.0, eval_window_s=0.6,
                 packet_drop_rate=0.0, gcs_timeout_s=5.0,
                 mode_transition_delay_s=0.1, ibit_cooldown_s=2.0,
                 intermittent_servos=None, gnss_degrade_during_ibit=False,
                 surface_faults=None,
                 verbose=False, fleet=None,
                 deterministic: bool = False, seed: int = 42,
                 record_path: Optional[str] = None,
                 fuzz_modes: Optional[set] = None,
                 fuzz_intensity: float = 0.0,
                 has_tau_elevons: bool = False,
                 x_tail: bool = False):

        self.vehicle_port = vehicle_port
        self.has_tau_elevons = has_tau_elevons
        self.x_tail = x_tail
        self.sysid = sysid
        self.ibit_pass = ibit_pass
        self.mist_flags = mistracking_flags if not ibit_pass else 0
        self.boot_monitors = boot_monitors or [0, 1, 2, 3, 4, 5]
        self.post_arm_monitors = post_arm_monitors or [10]
        self.trans_chance = transient_monitor_chance
        self.scale = ibit_duration_scale
        self.ibit_cycles = ibit_cycles
        self.boot_time = boot_time_s
        self.drop_rate = packet_drop_rate
        self.gcs_timeout = gcs_timeout_s
        self.mode_delay = mode_transition_delay_s
        self.ibit_cooldown = ibit_cooldown_s
        self.gnss_degrade_ibit = gnss_degrade_during_ibit
        self.verbose = verbose
        self.fleet = fleet

        # ── Deterministic clock & telemetry recorder ──────────────────
        self._clock = SimClock(deterministic=deterministic, seed=seed)
        self._recorder = TelemetryRecorder(record_path) if record_path else None

        # ── Vehicle state ─────────────────────────────────────────────
        self.flight_regime = FlightRegime.DISARMED
        self.act_state = ActuationState.OFF
        self.ibit_substate = IBITSubstate.BEGIN
        self.ibit_mon_status = 0
        self._ibit_active = False
        self._ibit_owns_servos = False  # When True, IBIT thread steps servos
        self._last_ibit_end = 0.0
        self._playback_direct = False  # Playback bypasses servo dynamics
        self._ibit_direct = False      # IBIT bypasses servo rate limiting

        # ── Real mistracking detection (firmware perform_monitoring()) ─
        self._mistrack_flags = 0       # accumulated mistracking bitmask
        self._tvc_consec_counters = {
            'left_tvc_upper': 0, 'left_tvc_lower': 0,
            'right_tvc_upper': 0, 'right_tvc_lower': 0,
        }

        # ── IBIT interruption support ─────────────────────────────────
        self._ibit_interrupted = False

        # ── Parameters ────────────────────────────────────────────────
        self._stored_params = dict(DEFAULT_PARAMS)
        self._active_params = dict(DEFAULT_PARAMS)

        # ── Sub-models ────────────────────────────────────────────────
        self.monitors = MonitorSystem(eval_window_s=eval_window_s)
        self._sensors = SensorSuite()
        self._bms = BatteryModel()
        self.servos = {n: Servo(name=n, is_tvc=('tvc' in n)) for n in SURFACE_NAMES}

        if intermittent_servos:
            for sname, prob in intermittent_servos.items():
                if sname in self.servos:
                    self.servos[sname].set_intermittent(prob)

        # Apply per-surface faults
        if surface_faults:
            for surface_name, fault_cfg in surface_faults.items():
                if surface_name in self.servos:
                    servo = self.servos[surface_name]
                    if fault_cfg.get('frozen'):
                        servo._frozen = True
                    if 'intermittent' in fault_cfg:
                        servo._intermittent = True
                        servo._intermittent_prob = fault_cfg['intermittent']
                    if 'bias_cdeg' in fault_cfg:
                        servo._bias = fault_cfg['bias_cdeg']
                    if 'rate_limit' in fault_cfg:
                        servo._rate_limit = fault_cfg['rate_limit']

        # ── GCS link ──────────────────────────────────────────────────
        self._last_gcs_hb = 0.0
        self._gcs_link_lost = True

        # ── Boot/power ────────────────────────────────────────────────
        self._powered = False
        self._booted = False
        self._boot_start = 0.0
        self._link_blackout_until = 0.0

        # ── HW selector ──────────────────────────────────────────────
        self._hw_config = 1
        self._hw_detections = 0

        # ── Networking ────────────────────────────────────────────────
        self._conn = None
        self._tx = None  # TelemetryManager
        self._running = False
        self._lock = threading.Lock()

        # ── Protocol fuzzer ───────────────────────────────────────────
        self._fuzzer = None
        if fuzz_intensity > 0 and fuzz_modes:
            from sim.fuzzer import ProtocolFuzzer
            # Fuzzer is created here but started in start() after connection is live
            self._fuzz_modes = fuzz_modes
            self._fuzz_intensity = fuzz_intensity

        _log(sysid, f"Sim v{__version__}  port={vehicle_port}  "
             f"ibit={'PASS' if ibit_pass else 'FAIL(0x%02X)' % self.mist_flags}  "
             f"cycles={ibit_cycles}  boot={boot_time_s}s")

    # ═══════════════════════════════════════════════════════════════════
    # Monitor condition registration
    # ═══════════════════════════════════════════════════════════════════

    def _register_monitor_conditions(self):
        """Register dynamically-evaluated monitor conditions.

        These supplement the static conditions in default_monitor_conditions()
        (monitors.py) and are re-registered on each power cycle since the
        MonitorSystem is recreated.

        Condition functions are no-arg lambdas that capture `self` and return
        True when the monitor should be SET.
        """
        m = self.monitors

        # ── Boot monitors (0-5) ───────────────────────────────────────
        # (Evaluated via default_monitor_conditions; force-set at power-on)

        # ── Post-ARM monitors (10-12) ─────────────────────────────────
        m.register_condition(11, lambda: False,
                             "Landing Gear Deployed")
        m.register_condition(12,
                             lambda: (self._active_params.get('USE_NEST', 0) == 1
                                      and self.flight_regime == FlightRegime.ARMED),
                             "Nest Connection Lost")

        # ── Runtime monitors (20-29) ──────────────────────────────────
        m.register_condition(20, lambda: self._gcs_link_lost and self._last_gcs_hb > 0,
                             "GCS Link Lost")
        m.register_condition(21, lambda: self._bms.pack_voltage < 22000,
                             "Low Battery Voltage")
        m.register_condition(22, lambda: any(s.temp > 80 for s in self.servos.values()),
                             "High Servo Temperature")
        m.register_condition(23,
                             lambda: (self._booted
                                      and self._sensors.ins_status < 3),  # INSStatus.FULL
                             "INS Degraded")
        m.register_condition(25,
                             lambda: (self.flight_regime == FlightRegime.ARMED
                                      and self._sensors.eng1_mode == 2
                                      and self._sensors.eng1_rpm < 30000),
                             "Engine 1 RPM Low")
        m.register_condition(26,
                             lambda: (self.flight_regime == FlightRegime.ARMED
                                      and self._sensors.eng2_mode == 2
                                      and self._sensors.eng2_rpm < 30000),
                             "Engine 2 RPM Low")
        m.register_condition(27, lambda: False,
                             "Actuation Bus Fault")
        m.register_condition(28, self._cell_imbalance,
                             "BMS Cell Imbalance")
        m.register_condition(29, lambda: any(s.cur > 5000 for s in self.servos.values()),
                             "Servo Overcurrent")

        # ── Safety-critical monitors (50-52) ──────────────────────────
        m.register_condition(50, lambda: False,
                             "Emergency Stop Commanded")
        m.register_condition(51, lambda: self._bms.pack_voltage < 18000,
                             "Power Bus Undervoltage")
        m.register_condition(52, lambda: any(s.temp > 95 for s in self.servos.values()),
                             "Thermal Shutdown Imminent")

    def _cell_imbalance(self):
        """Return True when BMS cell voltage spread exceeds 500 mV."""
        v = self._bms.get_cell_voltage()
        return (max(v) - min(v)) > 500

    # ═══════════════════════════════════════════════════════════════════
    # Boot / power
    # ═══════════════════════════════════════════════════════════════════

    def _boot_elapsed(self):
        return time.time() - self._boot_start if self._booted else 0

    def power_on(self):
        with self._lock:
            self._powered = True
            self._boot_start = time.time()
            self._booted = False
            self.flight_regime = FlightRegime.DISARMED
            self.act_state = ActuationState.OFF
            self.ibit_substate = IBITSubstate.BEGIN
            self.ibit_mon_status = 0
            self._ibit_active = False
            self._active_params = dict(self._stored_params)
            self._sensors.reset()
            self._bms.reset()
            self._gcs_link_lost = True
            self._last_gcs_hb = 0
            for s in self.servos.values():
                s.reset()
            self.monitors = MonitorSystem(eval_window_s=self.monitors.eval_window)
            self._register_monitor_conditions()
            # Force-set boot monitors (these represent hardware conditions
            # present at power-on that must be cleared by the operator)
            for mid in self.boot_monitors:
                self.monitors.force_set(mid)
            self._link_blackout_until = time.time() + self.boot_time * 0.7
        _log(self.sysid, f"Power ON -- booting ({self.boot_time}s)")
        threading.Thread(target=self._boot_sequence, daemon=True).start()

    def power_off(self):
        with self._lock:
            self._powered = False
            self._booted = False
            self.flight_regime = FlightRegime.DISARMED
            self.act_state = ActuationState.OFF
            self._bms.reset()
        _log(self.sysid, "Power OFF")

    def _boot_sequence(self):
        start = time.time()
        boot_dur = self.boot_time * self.scale
        while time.time() - start < boot_dur:
            frac = (time.time() - start) / boot_dur
            with self._lock:
                self._sensors.update_boot_progression(frac)
            time.sleep(0.1)
        with self._lock:
            if self._powered:
                self._booted = True
                self._sensors.finalize_boot()
                _log(self.sysid, "Boot complete")

    # ═══════════════════════════════════════════════════════════════════
    # Lifecycle
    # ═══════════════════════════════════════════════════════════════════

    def start(self):
        # Sim uses udpin (binds and listens on vehicle_port).
        # The patched connect_to_vehicle in run_sim.py uses udpout to send
        # to this port. This avoids the Windows CONNRESET issue because
        # the sim's socket is bound before any packets arrive.
        self._conn = mavutil.mavlink_connection(
            f"udpin:0.0.0.0:{self.vehicle_port}",
            dialect="pandion_vehicle_roadrunner",
            source_system=self.sysid, source_component=1)
        self._tx = TelemetryManager(self._conn, self.sysid)
        self._running = True
        if self._recorder:
            self._recorder.start()
        self.power_on()

        threading.Thread(target=self._telem_loop, daemon=True).start()
        threading.Thread(target=self._monitor_eval_loop, daemon=True).start()
        threading.Thread(target=self._sensor_loop, daemon=True).start()

        # Start protocol fuzzer if configured
        if hasattr(self, '_fuzz_modes') and self._fuzz_modes:
            from sim.fuzzer import ProtocolFuzzer
            self._fuzzer = ProtocolFuzzer(
                self._conn, modes=self._fuzz_modes,
                intensity=self._fuzz_intensity
            )
            self._fuzzer.start()

        # RX loop (blocking)
        try:
            while self._running:
                try:
                    msg = self._conn.recv_match(blocking=True, timeout=0.05)
                    if msg and msg.get_type() != 'BAD_DATA':
                        self._dispatch(msg)
                except OSError as e:
                    # WinError 10054: ICMP "port unreachable" from udpout client
                    # disconnecting. Safe to ignore — next packet will work.
                    if getattr(e, 'winerror', None) == 10054:
                        continue
                    raise
        except KeyboardInterrupt:
            pass
        finally:
            self._running = False
            if self._fuzzer:
                self._fuzzer.stop()
            if self._recorder:
                self._recorder.stop()

    def stop(self):
        self._running = False

    @property
    def clock(self) -> SimClock:
        """Simulation clock (deterministic or real-time)."""
        return self._clock

    def inject_relay_noise(self, amplitude=25.0):
        with self._lock:
            for s in self.servos.values():
                s.inject_noise(amplitude)

    # ═══════════════════════════════════════════════════════════════════
    # Message dispatch
    # ═══════════════════════════════════════════════════════════════════

    def _dispatch(self, msg):
        if not self._powered:
            return
        t = msg.get_type()
        if self.verbose:
            _log(self.sysid, f"RX {t}")

        if t == 'HEARTBEAT':
            self._last_gcs_hb = time.time()
            with self._lock:
                self._gcs_link_lost = False
        elif t == 'COMMAND_LONG':
            self._handle_command(msg)
        elif t == 'PARAM_REQUEST_READ':
            self._handle_param_read(msg)
        elif t == 'PARAM_SET':
            self._handle_param_set(msg)
        elif t == 'PANDION_RR_ACTUATION_REQUEST_MODE':
            self._handle_mode_request(msg)
        elif t == 'PANDION_MONITOR_OVERRIDE_CMD':
            self._handle_monitor_override(msg)
        elif t == 'PANDION_RR_PLAYBACK_COMMAND':
            self._handle_playback_command(msg)

    def _handle_command(self, msg):
        if msg.command != 400:
            return
        arm = int(msg.param1)
        force = int(getattr(msg, 'param2', 0)) == ARM_FORCE_MAGIC

        with self._lock:
            if arm == 1:
                s, _, _ = self.monitors.get_state()
                if s and not force:
                    _log(self.sysid, f"ARM REJECTED -- {len(s)} monitors")
                    self._tx.command_ack(400, 1)
                    # Send STATUSTEXT identifying blocking monitors for debug visibility
                    self._tx.statustext(
                        f"ARM rejected: {len(s)} monitor(s) SET — "
                        f"IDs: {sorted(s)}"
                    )
                    return
                self.flight_regime = FlightRegime.ARMED
                if self.has_tau_elevons:
                    self.act_state = ActuationState.POS_CHECK
                    self.ibit_substate = IBITSubstate.BEGIN
                    self.ibit_mon_status = 0
                    _log(self.sysid, "ARMED -> POS_CHECK" + (" (FORCED)" if force else ""))
                    self._tx.command_ack(400, 0)
                    self._tx.statustext("Vehicle ARMED")
                    threading.Thread(target=self._pos_check_sequence, daemon=True).start()
                else:
                    self.act_state = ActuationState.OPERATE
                    self.ibit_substate = IBITSubstate.BEGIN
                    self.ibit_mon_status = 0
                    _log(self.sysid, "ARMED -> OPERATE" + (" (FORCED)" if force else ""))
                    self._tx.command_ack(400, 0)
                    self._tx.statustext("Vehicle ARMED")
            else:
                if self._ibit_active:
                    _log(self.sysid, "DISARM REJECTED -- IBIT active")
                    self._tx.command_ack(400, 1)
                    return
                self.flight_regime = FlightRegime.DISARMED
                self.act_state = ActuationState.OFF
                _log(self.sysid, "DISARMED -> OFF")
                self._tx.command_ack(400, 0)
                self._tx.statustext("Vehicle DISARMED")

    def _pos_check_sequence(self):
        """TAU Mk2 elevon position verification delay."""
        time.sleep(2.0)
        with self._lock:
            if self.act_state == ActuationState.POS_CHECK:
                self.act_state = ActuationState.OPERATE
                _log(self.sysid, "POS_CHECK -> OPERATE")

    def _handle_param_read(self, msg):
        name = _decode_param_id(msg.param_id)
        self._tx.param_value(name, float(self._active_params.get(name, 0)))

    def _handle_param_set(self, msg):
        name = _decode_param_id(msg.param_id)
        val = int(msg.param_value)
        with self._lock:
            self._stored_params[name] = val
            if name not in REBOOT_REQUIRED_PARAMS:
                self._active_params[name] = val
        rq = " (reboot required)" if name in REBOOT_REQUIRED_PARAMS else ""
        _log(self.sysid, f"PARAM {name} = {val}{rq}")
        self._tx.param_value(name, float(val))

    def _handle_mode_request(self, msg):
        req = msg.requested_mode
        N = ActuationState.NAMES

        with self._lock:
            # Fix #4: Firmware requires armed state for non-OFF mode requests
            _armed = (self.flight_regime >= FlightRegime.ARMED)
            if not _armed and req != ActuationState.OFF:
                # Real firmware silently ignores, but send STATUSTEXT for debug visibility
                target_name = ActuationState.NAMES.get(req, str(req))
                self._tx.statustext(
                    f"Mode request rejected: {target_name} requires vehicle to be ARMED"
                )
                return

            # Fix #5: Nest-connected restricts to IBIT (and OFF) only
            _use_nest_active = (
                self._active_params.get('USE_NEST', 0) == 1
                and self.flight_regime >= FlightRegime.ARMED
            )
            if _use_nest_active and req != ActuationState.IBIT and req != ActuationState.OFF:
                target_name = ActuationState.NAMES.get(req, str(req))
                self._tx.statustext(
                    f"Mode request rejected: {target_name} not allowed when nest is connected"
                )
                return

            cur = self.act_state

            # ── Fix #1: IBIT interruption (firmware allows mode changes during IBIT) ──
            if cur == ActuationState.IBIT and req != ActuationState.IBIT:
                self._ibit_interrupted = True
                self._ibit_active = False  # Signal the IBIT thread to stop
                # Wait briefly for IBIT thread to notice
                time.sleep(0.05)
                self.act_state = req
                self._playback_direct = (req == ActuationState.PLAYBACK)
                self._mode_transition_blackout = time.time() + 0.1
                _log(self.sysid, f"IBIT INTERRUPTED: {N.get(cur, '?')} -> {N.get(req, '?')}")
                self._tx.statustext(f"Mode: {N.get(req, str(req))}")
                return

            # Use centralized transition table; OFF is always allowed
            valid = (
                req == ActuationState.OFF or
                (cur, req) in ActuationState.VALID_TRANSITIONS
            )

            if valid:
                # IBIT cooldown guard
                if req == ActuationState.IBIT:
                    since = time.time() - self._last_ibit_end
                    if self._last_ibit_end > 0 and since < self.ibit_cooldown * self.scale:
                        remaining = (self.ibit_cooldown * self.scale) - since
                        _log(self.sysid, f"IBIT REJECTED -- cooldown ({remaining:.1f}s remaining)")
                        self._tx.statustext(
                            f"IBIT rejected: cooldown active ({remaining:.1f}s remaining)"
                        )
                        return

                time.sleep(self.mode_delay * self.scale)
                self.act_state = req
                # Track playback direct mode for servo bypass
                self._playback_direct = (req == ActuationState.PLAYBACK)
                # Brief telemetry blackout during transition (1-2 frames at 20Hz)
                self._mode_transition_blackout = time.time() + 0.05
                _log(self.sysid, f"Mode: {N.get(cur, '?')} -> {N.get(req, '?')}")
                self._tx.statustext(f"Mode: {N.get(req, str(req))}")

                if req == ActuationState.IBIT:
                    self._ibit_active = True
                    self._ibit_direct = False  # IBIT uses real servo dynamics for mistracking detection
                    threading.Thread(target=self._run_ibit, daemon=True).start()
            else:
                from_name = N.get(cur, str(cur))
                to_name = N.get(req, str(req))
                _log(self.sysid, f"Mode REJECTED: {from_name} -> {to_name}")
                self._tx.statustext(
                    f"Mode request rejected: {from_name} -> {to_name} is not a valid transition"
                )

    def _handle_monitor_override(self, msg):
        if msg.override_cmd == MONITOR_OVERRIDE_CANCEL:
            # Cancel override, return to normal monitoring
            self.monitors.cancel_override(msg.monitor_id)
        elif msg.override_cmd == MONITOR_OVERRIDE_SUPPRESS:
            # Override to healthy (suppress fault) — clear from SET, mark overridden
            self.monitors.clear(msg.monitor_id)
        elif msg.override_cmd == MONITOR_OVERRIDE_FORCE_FAULT:
            # Override to faulted — add to SET
            self.monitors.force_set(msg.monitor_id)

    def _handle_playback_command(self, msg):
        """Apply playback commands directly (no slew limiting).

        Firmware applies playback commands directly to servo outputs,
        bypassing the rate-limited servo dynamics.  We set both .cmd
        and .fb so the servo step() sees zero error and does not slew.
        """
        with self._lock:
            pairs = [
                ('left_elevon',     msg.left_elevon_ted_command_cdeg),
                ('right_elevon',    msg.right_elevon_ted_command_cdeg),
                ('dorsal_rudder',   msg.upper_rudder_tel_command_cdeg),
                ('ventral_rudder',  msg.lower_rudder_tel_command_cdeg),
                ('left_tvc_upper',  msg.left_tvc_upper_command_cdeg),
                ('left_tvc_lower',  msg.left_tvc_lower_command_cdeg),
                ('right_tvc_upper', msg.right_tvc_upper_command_cdeg),
                ('right_tvc_lower', msg.right_tvc_lower_command_cdeg),
            ]
            for name, val in pairs:
                self.servos[name].cmd = val
                self.servos[name].fb = val

    # ═══════════════════════════════════════════════════════════════════
    # IBIT
    # ═══════════════════════════════════════════════════════════════════

    # Surface-to-bitmask mapping (from MistrackingFlags)
    _SURFACE_FLAGS = {
        'left_elevon': 64, 'right_elevon': 128,
        'dorsal_rudder': 1, 'ventral_rudder': 2,
        'left_tvc_upper': 4, 'left_tvc_lower': 8,
        'right_tvc_upper': 16, 'right_tvc_lower': 32,
    }
    _MISTRACK_THRESHOLD = 500  # cdeg
    _TVC_CONSEC_LIMIT = 5      # cycles

    def _check_mistracking(self):
        """Firmware-accurate mistracking detection (perform_monitoring()).

        Called every tick during IBIT phases ELEVON, RUDDERS, TVC.
        - Aero surfaces (elevon + rudder): instantaneous fail if |cmd - fb| > 500 cdeg
        - TVC servos: consecutive counter -- 5 consecutive ticks above threshold
        """
        for name, servo in self.servos.items():
            error = abs(servo.command - servo.fb)
            flag = self._SURFACE_FLAGS.get(name, 0)

            if 'tvc' in name:
                # TVC: consecutive counter
                if error > self._MISTRACK_THRESHOLD:
                    self._tvc_consec_counters[name] += 1
                    if self._tvc_consec_counters[name] >= self._TVC_CONSEC_LIMIT:
                        self._mistrack_flags |= flag
                else:
                    self._tvc_consec_counters[name] = 0
            else:
                # Aero: instantaneous
                if error > self._MISTRACK_THRESHOLD:
                    self._mistrack_flags |= flag

    def _run_ibit(self):
        # Reset mistracking state at the start of IBIT
        self._mistrack_flags = 0
        for k in self._tvc_consec_counters:
            self._tvc_consec_counters[k] = 0
        self._ibit_interrupted = False

        # Set fast servo rate limit for IBIT (physical servo speed, not manual limit)
        # Real servos move at ~40000 cdeg/s; the 1500 cdeg/s manual limit doesn't apply during IBIT
        IBIT_SERVO_RATE = 40000.0
        saved_rates = {}
        for name, servo in self.servos.items():
            saved_rates[name] = servo._rate_limit
            servo._rate_limit = IBIT_SERVO_RATE

        try:
            self._ibit_owns_servos = True
            for cycle in range(self.ibit_cycles):
                if cycle > 0:
                    _log(self.sysid, f"IBIT cycle {cycle + 1}/{self.ibit_cycles}")
                if not self._run_ibit_cycle():
                    break
        finally:
            self._ibit_owns_servos = False
            # Restore original rate limits
            for name, servo in self.servos.items():
                servo._rate_limit = saved_rates.get(name, servo._rate_limit)

        with self._lock:
            # Use REAL computed mistracking OR the forced flags (for scenario testing)
            self.ibit_mon_status = self._mistrack_flags | self.mist_flags

            for s in self.servos.values():
                s.unfreeze()
                s.cmd = 0

            if self._ibit_interrupted:
                # Transition to the interrupted-requested mode is already
                # handled in _handle_mode_request; just clean up.
                pass
            else:
                self.act_state = ActuationState.OPERATE

            self.ibit_substate = IBITSubstate.DONE
            self._ibit_active = False
            self._ibit_direct = False
            self._last_ibit_end = time.time()

        result = "PASS" if self.ibit_mon_status == 0 else f"FAIL(0x{self.ibit_mon_status:02X})"
        if self._ibit_interrupted:
            _log(self.sysid, f"IBIT INTERRUPTED  [{result}]")
            self._tx.statustext(f"IBIT INTERRUPTED {result}")
        else:
            _log(self.sysid, f"IBIT -> OPERATE  [{result}]")
            self._tx.statustext(f"IBIT {result}")

    def _run_ibit_cycle(self):
        with self._lock:
            self.ibit_mon_status = 0
            for s in self.servos.values():
                s.cmd = 0
                s.unfreeze()

        if self.gnss_degrade_ibit:
            with self._lock:
                self._sensors.degrade_gnss()

        for phase in IBITSubstate.SEQUENCE:
            with self._lock:
                if self.act_state != ActuationState.IBIT or not self._ibit_active:
                    return False
                self.ibit_substate = phase
                if self.monitors.has_safety_critical():
                    _log(self.sysid, "IBIT ABORT -- safety-critical monitor")
                    return False

            # DONE: firmware transitions immediately from TVC -> OPERATE.
            # No COMPLETE state delay.  Just break out of the phase loop.
            if phase == IBITSubstate.DONE:
                break

            _log(self.sysid, f"IBIT: {IBITSubstate.NAMES[phase]}")
            self._tx.statustext(f"IBIT: {IBITSubstate.NAMES[phase]}")

            dur = IBIT_PHASE_DURATIONS.get(phase, 0) * self.scale

            if phase == IBITSubstate.BEGIN:
                # Immediate: zero commands, enable servos, transition
                with self._lock:
                    for s in self.servos.values():
                        s.cmd = 0.0
                continue  # No sleep, immediate transition to SETTLE

            elif phase == IBITSubstate.SETTLE:
                # Zero commands for settle duration
                self._run_ibit_zero_settle(dur)

            elif phase == IBITSubstate.ELEVON:
                self._run_ibit_elevon(dur)

            elif phase == IBITSubstate.RUDDERS:
                if not self.x_tail:
                    self._run_ibit_rudders(dur)
                else:
                    # X-tail: skip rudders, go directly to TVC
                    self.ibit_substate = IBITSubstate.TVC

            elif phase == IBITSubstate.TVC:
                self._run_ibit_tvc(dur)

        if self.gnss_degrade_ibit:
            with self._lock:
                self._sensors.restore_gnss()
        return True

    # ── Firmware-accurate IBIT command functions ──────────────────────

    @staticmethod
    def _ibit_linear_function(percent):
        """
        Exact replica of ibit_linear_function() from actuation.c.

        Triangle wave:
          0-25%:  lerp 0 -> -1
          25-75%: lerp -1 -> +1
          75-100%: lerp +1 -> 0
        """
        if percent < 0.0 or percent > 1.0:
            return 0.0
        if percent < 0.25:
            return -(percent * 4.0)
        elif percent < 0.75:
            stage = percent - 0.25
            return (stage * 4.0) - 1.0
        else:
            stage = percent - 0.75
            return -(stage * 4.0) + 1.0

    def _run_ibit_zero_settle(self, dur):
        """IBIT_WAIT_FOR_SETTLE: zero all commands for dur seconds."""
        dt = 0.01
        start = time.time()
        while (time.time() - start) < dur:
            loop_start = time.time()
            with self._lock:
                if self.act_state != ActuationState.IBIT or not self._ibit_active:
                    return
                # 1. Set commands
                for s in self.servos.values():
                    s.cmd = 0.0
                # 2. Step servo dynamics
                now = time.time()
                elev_load = abs(self.servos['left_elevon'].fb) + abs(self.servos['right_elevon'].fb)
                for sname, servo in self.servos.items():
                    coupling = elev_load * 0.01 if 'rudder' in sname else 0.0
                    servo.step(dt, now, coupling, direct=False)
                # 3. Check mistracking (sees current tick's feedback)
                self._check_mistracking()
            elapsed_tick = time.time() - loop_start
            sleep_time = max(0, dt - elapsed_tick)
            time.sleep(sleep_time)

    def _run_ibit_elevon(self, dur):
        """
        IBIT_ELEVON phase from actuation.c:
        Applies ibit_linear_function() as IBIT_AERO_PitchAccelCmd.
        This drives elevons in opposite directions (pitch command).
        Nest coefficient: 0.75.

        We approximate the ControlAllocation output by mapping the
        [-1,+1] multiplier directly to elevon commands.
        """
        dt = 0.01
        nest = self._active_params.get('USE_NEST', 0) == 0
        coeff = IBIT_NEST_COEFFS['elev'] if nest else 1.0
        max_cdeg = SERVO_HARD_LIMITS['elevon']

        # Inject mistracking for failing surfaces
        if not self.ibit_pass:
            with self._lock:
                for flag, sname in MistrackingFlags.FLAG_TO_SURFACE.items():
                    if (self.mist_flags & flag) and 'elevon' in sname:
                        self.servos[sname].freeze()

        start = time.time()
        while (time.time() - start) < dur:
            loop_start = time.time()
            with self._lock:
                if self.act_state != ActuationState.IBIT or not self._ibit_active:
                    return
                pct = (time.time() - start) / dur
                mult = self._ibit_linear_function(pct) * coeff
                # 1. Set commands -- elevons move in opposite directions for pitch
                self.servos['left_elevon'].cmd = mult * max_cdeg
                self.servos['right_elevon'].cmd = -mult * max_cdeg
                # 2. Step ALL servo dynamics
                now = time.time()
                elev_load = abs(self.servos['left_elevon'].fb) + abs(self.servos['right_elevon'].fb)
                for sname, servo in self.servos.items():
                    coupling = elev_load * 0.01 if 'rudder' in sname else 0.0
                    servo.step(dt, now, coupling, direct=False)
                # 3. Check mistracking (sees current tick's feedback)
                self._check_mistracking()
            elapsed_tick = time.time() - loop_start
            sleep_time = max(0, dt - elapsed_tick)
            time.sleep(sleep_time)

    def _run_ibit_rudders(self, dur):
        """
        IBIT_RUDDERS phase from actuation.c:
        Applies ibit_linear_function() as IBIT_AERO_RollAccelCmd.
        Drives rudders.
        Nest coefficient: 0.05 (very small when connected to nest).
        """
        dt = 0.01
        nest = self._active_params.get('USE_NEST', 0) == 0
        coeff = IBIT_NEST_COEFFS['rudd'] if nest else 1.0
        max_cdeg = SERVO_HARD_LIMITS['rudder']

        if not self.ibit_pass:
            with self._lock:
                for flag, sname in MistrackingFlags.FLAG_TO_SURFACE.items():
                    if (self.mist_flags & flag) and 'rudder' in sname:
                        self.servos[sname].freeze()

        start = time.time()
        while (time.time() - start) < dur:
            loop_start = time.time()
            with self._lock:
                if self.act_state != ActuationState.IBIT or not self._ibit_active:
                    return
                pct = (time.time() - start) / dur
                mult = self._ibit_linear_function(pct) * coeff
                # 1. Set commands
                self.servos['dorsal_rudder'].cmd = mult * max_cdeg
                self.servos['ventral_rudder'].cmd = -mult * max_cdeg
                # 2. Step ALL servo dynamics
                now = time.time()
                elev_load = abs(self.servos['left_elevon'].fb) + abs(self.servos['right_elevon'].fb)
                for sname, servo in self.servos.items():
                    coupling = elev_load * 0.01 if 'rudder' in sname else 0.0
                    servo.step(dt, now, coupling, direct=False)
                # 3. Check mistracking (sees current tick's feedback)
                self._check_mistracking()
            elapsed_tick = time.time() - loop_start
            sleep_time = max(0, dt - elapsed_tick)
            time.sleep(sleep_time)

    def _run_ibit_tvc(self, dur):
        """
        IBIT_TVC phase from actuation.c:
        Radial sweep using cos/sin with amplitude envelope.

        From firmware:
          angle sweeps 0 -> 2*pi over the full phase duration
          Radial amplitude:
            0-25%:   ramp 0 -> 1
            25-75%:  full amplitude 1.0
            75-100%: ramp 1 -> 0
          Square-wave clipping: radial = min(1/|cos|, 1/|sin|) clamped to 1.0
          Upper TVC commands = radial * cos(angle) * max_cdeg
          Lower TVC commands = radial * sin(angle) * max_cdeg
        Nest coefficient: 0.60.
        """
        dt = 0.01
        nest = self._active_params.get('USE_NEST', 0) == 0
        coeff = IBIT_NEST_COEFFS['tvc'] if nest else 1.0
        max_cdeg = SERVO_HARD_LIMITS['tvc']

        if not self.ibit_pass:
            with self._lock:
                for flag, sname in MistrackingFlags.FLAG_TO_SURFACE.items():
                    if (self.mist_flags & flag) and 'tvc' in sname:
                        self.servos[sname].freeze()

        start = time.time()
        while (time.time() - start) < dur:
            loop_start = time.time()
            with self._lock:
                if self.act_state != ActuationState.IBIT or not self._ibit_active:
                    return
                pct = (time.time() - start) / dur
                angle = 2.0 * math.pi * pct

                # Radial amplitude envelope
                if pct < 0.25:
                    radial = pct / 0.25         # ramp 0 -> 1
                elif pct < 0.75:
                    radial = 1.0                # full amplitude
                else:
                    radial = (1.0 - pct) / 0.25  # ramp 1 -> 0

                # Square-wave clipping from firmware
                cos_a = math.cos(angle)
                sin_a = math.sin(angle)
                sq_cos = (1.0 / abs(cos_a)) if abs(cos_a) > 1e-6 else 1e6
                sq_sin = (1.0 / abs(sin_a)) if abs(sin_a) > 1e-6 else 1e6
                sq_clip = min(sq_cos, sq_sin, 1.0)
                radial *= sq_clip

                radial = max(-1.0, min(1.0, radial))
                radial *= coeff

                upper_cmd = radial * cos_a * max_cdeg
                lower_cmd = radial * sin_a * max_cdeg

                self.servos['left_tvc_upper'].cmd = upper_cmd
                self.servos['left_tvc_lower'].cmd = lower_cmd
                self.servos['right_tvc_upper'].cmd = upper_cmd
                self.servos['right_tvc_lower'].cmd = lower_cmd

                # 2. Step ALL servo dynamics
                now = time.time()
                elev_load = abs(self.servos['left_elevon'].fb) + abs(self.servos['right_elevon'].fb)
                for sname, servo in self.servos.items():
                    coupling = elev_load * 0.01 if 'rudder' in sname else 0.0
                    servo.step(dt, now, coupling, direct=False)

                # 3. Check mistracking (sees current tick's feedback)
                self._check_mistracking()

            elapsed_tick = time.time() - loop_start
            sleep_time = max(0, dt - elapsed_tick)
            time.sleep(sleep_time)

    # ═══════════════════════════════════════════════════════════════════
    # Background loops
    # ═══════════════════════════════════════════════════════════════════

    def _telem_loop(self):
        intervals = {
            'hb':  1.0 / RATE_HEARTBEAT,
            'ps':  1.0 / RATE_PANDION_STATUS,
            'act': 1.0 / RATE_ACTUATION,
            'mon': 1.0 / RATE_MONITORS,
            'eng': 1.0 / RATE_ENGINE,
            'bms': 1.0 / RATE_BMS,
            'wca': 1.0 / RATE_WCA,
            'pdu': 1.0 / RATE_PDU,
            'hw':  1.0 / RATE_HW_SELECTOR,
        }
        last = {k: 0.0 for k in intervals}
        dt = 0.01
        self._mode_transition_blackout = 0.0

        while self._running:
            now = time.time()

            # ── Gate 1: not powered or not booted ─────────────────────
            if not self._powered or not self._booted or now < self._link_blackout_until:
                time.sleep(dt)
                continue

            # ── Gate 2: no telemetry until GCS sends first heartbeat ──
            # Real Pandion uses udpin -- it only knows where to send
            # telemetry after receiving a packet from the GCS.
            if self._last_gcs_hb == 0:
                time.sleep(dt)
                continue

            # ── Gate 3: mode transition blackout (1-2 frames) ─────────
            if now < self._mode_transition_blackout:
                time.sleep(dt)
                continue

            # ── Step servos (only when actuation is active) ───────────
            with self._lock:
                act = self.act_state
                fr = self.flight_regime

                if act in (ActuationState.OPERATE, ActuationState.IBIT,
                           ActuationState.PLAYBACK, ActuationState.MANUAL):
                    if not self._ibit_owns_servos:
                        # Normal servo stepping (telem loop owns servos)
                        direct = self._playback_direct or self._ibit_direct
                        elev_load = abs(self.servos['left_elevon'].fb) + abs(self.servos['right_elevon'].fb)
                        for sname, servo in self.servos.items():
                            coupling = elev_load * 0.01 if 'rudder' in sname else 0.0
                            servo.step(dt, now, coupling, direct=direct)
                    # else: IBIT thread is stepping servos -- skip here to avoid double-stepping
                else:
                    # OFF mode: servos unpowered, feedback drifts to trim
                    for servo in self.servos.values():
                        servo.fb += (servo._trim_offset - servo.fb) * 0.1 * dt
                        servo.cur = random.gauss(5, 2)  # quiescent ~5mA
                        servo.vel = 0.0

                isub = self.ibit_substate
                imon = self.ibit_mon_status
                svs = self.servos

            drop = self.drop_rate > 0.0 and random.random() < self.drop_rate
            _mon_state = None  # lazy-computed once per tick if needed

            if not drop:
                # ── Heartbeat: always (even before GCS, but we gated above) ──
                if now - last['hb'] >= intervals['hb']:
                    self._tx.heartbeat()
                    last['hb'] = now

                # ── PANDION_STATUS: always after boot ─────────────────
                if now - last['ps'] >= intervals['ps']:
                    self._tx.pandion_status(fr, self._sensors,
                                            self._sensors.eng1_mode, self._sensors.eng2_mode)
                    last['ps'] = now

                # ── ACTUATION_SYS_STATUS: always, but content depends on mode ─
                if now - last['act'] >= intervals['act']:
                    self._tx.actuation_sys_status(act, isub, imon, svs)
                    last['act'] = now

                # ── MONITOR_CURRENT_STATUS: always ────────────────────
                if now - last['mon'] >= intervals['mon']:
                    if _mon_state is None:
                        _mon_state = self.monitors.get_state()
                    s, sg, o = _mon_state
                    self._tx.monitor_current_status(s, sg, o)
                    last['mon'] = now

                # ── ENGINE_STATUS: always, values depend on relay state ─
                if now - last['eng'] >= intervals['eng']:
                    self._tx.engine_status(self._sensors, self._powered)
                    last['eng'] = now

                # ── BMS: always ───────────────────────────────────────
                if now - last['bms'] >= intervals['bms']:
                    self._tx.bms_data(self._bms)
                    last['bms'] = now

                # ── WCA: always ───────────────────────────────────────
                if now - last['wca'] >= intervals['wca']:
                    if _mon_state is None:
                        _mon_state = self.monitors.get_state()
                    s, _, _ = _mon_state
                    eid, ets, efl = self.monitors.get_event()
                    self._tx.wca_monitor_status(s, eid, ets, efl)
                    last['wca'] = now

                # ── PDU + HW: low rate ────────────────────────────────
                if now - last['pdu'] >= intervals['pdu']:
                    self._tx.pdu_telemetry(self._bms)
                    last['pdu'] = now
                if now - last['hw'] >= intervals['hw']:
                    self._tx.hw_selector(self._hw_config, self._hw_detections)
                    last['hw'] = now

            time.sleep(dt)

    def _monitor_eval_loop(self):
        while self._running:
            if self._powered and self._booted:
                self.monitors.evaluate(self, default_monitor_conditions)
            time.sleep(0.3)

    def _sensor_loop(self):
        while self._running:
            if self._powered:
                with self._lock:
                    # GCS timeout
                    if self._last_gcs_hb > 0:
                        self._gcs_link_lost = (
                            time.time() - self._last_gcs_hb > self.gcs_timeout
                        )
                    # Battery
                    total_cur = sum(s.cur for s in self.servos.values())
                    self._bms.step(0.5, total_cur)
            time.sleep(0.5)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _decode_param_id(raw):
    if isinstance(raw, bytes):
        return raw.decode('utf-8').rstrip('\x00')
    return str(raw).rstrip('\x00')
