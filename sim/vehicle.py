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
)
from .models.servo import Servo
from .models.battery import BatteryModel
from .models.monitors import MonitorSystem, default_monitor_conditions
from .models.sensors import SensorSuite
from .telemetry import TelemetryManager


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
                 verbose=False, fleet=None):

        self.vehicle_port = vehicle_port
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

        # ── Vehicle state ─────────────────────────────────────────────
        self.flight_regime = FlightRegime.DISARMED
        self.act_state = ActuationState.OFF
        self.ibit_substate = IBITSubstate.BEGIN
        self.ibit_mon_status = 0
        self._ibit_active = False
        self._last_ibit_end = 0.0

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

        _log(sysid, f"Sim v4  port={vehicle_port}  "
             f"ibit={'PASS' if ibit_pass else 'FAIL(0x%02X)' % self.mist_flags}  "
             f"cycles={ibit_cycles}  boot={boot_time_s}s")

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
            self._gcs_link_lost = True
            self._last_gcs_hb = 0
            for s in self.servos.values():
                s.reset()
            self.monitors = MonitorSystem(eval_window_s=self.monitors.eval_window)
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
        self.power_on()

        threading.Thread(target=self._telem_loop, daemon=True).start()
        threading.Thread(target=self._monitor_eval_loop, daemon=True).start()
        threading.Thread(target=self._sensor_loop, daemon=True).start()

        # RX loop (blocking)
        try:
            while self._running:
                msg = self._conn.recv_match(blocking=True, timeout=0.05)
                if msg and msg.get_type() != 'BAD_DATA':
                    self._dispatch(msg)
        except KeyboardInterrupt:
            pass
        finally:
            self._running = False

    def stop(self):
        self._running = False

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
                    return
                self.flight_regime = FlightRegime.ARMED
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
            cur = self.act_state
            valid = (
                (req == ActuationState.PLAYBACK and cur == ActuationState.OPERATE) or
                (req == ActuationState.IBIT and cur == ActuationState.PLAYBACK) or
                (req == ActuationState.OPERATE and cur in (
                    ActuationState.IBIT, ActuationState.PLAYBACK, ActuationState.MANUAL
                )) or
                req == ActuationState.OFF
            )

            if valid:
                # IBIT cooldown guard
                if req == ActuationState.IBIT:
                    since = time.time() - self._last_ibit_end
                    if self._last_ibit_end > 0 and since < self.ibit_cooldown * self.scale:
                        _log(self.sysid, f"IBIT REJECTED -- cooldown")
                        return

                time.sleep(self.mode_delay * self.scale)
                self.act_state = req
                # Brief telemetry blackout during transition (1-2 frames at 20Hz)
                self._mode_transition_blackout = time.time() + 0.05
                _log(self.sysid, f"Mode: {N.get(cur, '?')} -> {N.get(req, '?')}")
                self._tx.statustext(f"Mode: {N.get(req, str(req))}")

                if req == ActuationState.IBIT:
                    self._ibit_active = True
                    threading.Thread(target=self._run_ibit, daemon=True).start()
            else:
                _log(self.sysid, f"Mode REJECTED: {N.get(cur, '?')} -> {N.get(req, '?')}")

    def _handle_monitor_override(self, msg):
        if msg.override_cmd == 2:
            self.monitors.clear(msg.monitor_id)
        elif msg.override_cmd == 0:
            self.monitors.cancel_override(msg.monitor_id)
        elif msg.override_cmd == 1:
            self.monitors.force_set(msg.monitor_id)

    def _handle_playback_command(self, msg):
        with self._lock:
            self.servos['left_elevon'].cmd = msg.left_elevon_ted_command_cdeg
            self.servos['right_elevon'].cmd = msg.right_elevon_ted_command_cdeg
            self.servos['dorsal_rudder'].cmd = msg.upper_rudder_tel_command_cdeg
            self.servos['ventral_rudder'].cmd = msg.lower_rudder_tel_command_cdeg
            self.servos['left_tvc_upper'].cmd = msg.left_tvc_upper_command_cdeg
            self.servos['left_tvc_lower'].cmd = msg.left_tvc_lower_command_cdeg
            self.servos['right_tvc_upper'].cmd = msg.right_tvc_upper_command_cdeg
            self.servos['right_tvc_lower'].cmd = msg.right_tvc_lower_command_cdeg

    # ═══════════════════════════════════════════════════════════════════
    # IBIT
    # ═══════════════════════════════════════════════════════════════════

    def _run_ibit(self):
        for cycle in range(self.ibit_cycles):
            if cycle > 0:
                _log(self.sysid, f"IBIT cycle {cycle + 1}/{self.ibit_cycles}")
            if not self._run_ibit_cycle():
                break

        with self._lock:
            if not self.ibit_pass:
                self.ibit_mon_status = self.mist_flags
            else:
                computed = 0
                for flag, sname in MistrackingFlags.FLAG_TO_SURFACE.items():
                    if self.servos[sname].is_mistracking:
                        computed |= flag
                self.ibit_mon_status = computed

            for s in self.servos.values():
                s.unfreeze()
                s.cmd = 0
            self.act_state = ActuationState.OPERATE
            self.ibit_substate = IBITSubstate.DONE
            self._ibit_active = False
            self._last_ibit_end = time.time()

        result = "PASS" if self.ibit_mon_status == 0 else f"FAIL(0x{self.ibit_mon_status:02X})"
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
                if self.act_state != ActuationState.IBIT:
                    return False
                self.ibit_substate = phase
                if self.monitors.has_safety_critical():
                    _log(self.sysid, "IBIT ABORT -- safety-critical monitor")
                    return False

            _log(self.sysid, f"IBIT: {IBITSubstate.NAMES[phase]}")
            self._tx.statustext(f"IBIT: {IBITSubstate.NAMES[phase]}")

            dur = IBIT_PHASE_DURATIONS[phase] * self.scale

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
                self._run_ibit_rudders(dur)

            elif phase == IBITSubstate.TVC:
                self._run_ibit_tvc(dur)

            elif phase == IBITSubstate.DONE:
                # Immediate transition to OPERATE
                continue

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
        elapsed = 0.0
        while elapsed < dur:
            with self._lock:
                if self.act_state != ActuationState.IBIT:
                    return
                for s in self.servos.values():
                    s.cmd = 0.0
            time.sleep(dt)
            elapsed += dt

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
        elapsed = 0.0
        nest = self._active_params.get('USE_NEST', 0) == 0
        coeff = IBIT_NEST_COEFFS['elev'] if nest else 1.0
        max_cdeg = SERVO_HARD_LIMITS['elevon']

        # Inject mistracking for failing surfaces
        if not self.ibit_pass:
            with self._lock:
                for flag, sname in MistrackingFlags.FLAG_TO_SURFACE.items():
                    if (self.mist_flags & flag) and 'elevon' in sname:
                        self.servos[sname].freeze()

        while elapsed < dur:
            with self._lock:
                if self.act_state != ActuationState.IBIT:
                    return
                pct = elapsed / dur
                mult = self._ibit_linear_function(pct) * coeff
                # Elevons move in opposite directions for pitch
                self.servos['left_elevon'].cmd = mult * max_cdeg
                self.servos['right_elevon'].cmd = -mult * max_cdeg
            time.sleep(dt)
            elapsed += dt

    def _run_ibit_rudders(self, dur):
        """
        IBIT_RUDDERS phase from actuation.c:
        Applies ibit_linear_function() as IBIT_AERO_RollAccelCmd.
        Drives rudders.
        Nest coefficient: 0.05 (very small when connected to nest).
        """
        dt = 0.01
        elapsed = 0.0
        nest = self._active_params.get('USE_NEST', 0) == 0
        coeff = IBIT_NEST_COEFFS['rudd'] if nest else 1.0
        max_cdeg = SERVO_HARD_LIMITS['rudder']

        if not self.ibit_pass:
            with self._lock:
                for flag, sname in MistrackingFlags.FLAG_TO_SURFACE.items():
                    if (self.mist_flags & flag) and 'rudder' in sname:
                        self.servos[sname].freeze()

        while elapsed < dur:
            with self._lock:
                if self.act_state != ActuationState.IBIT:
                    return
                pct = elapsed / dur
                mult = self._ibit_linear_function(pct) * coeff
                self.servos['dorsal_rudder'].cmd = mult * max_cdeg
                self.servos['ventral_rudder'].cmd = -mult * max_cdeg
            time.sleep(dt)
            elapsed += dt

    def _run_ibit_tvc(self, dur):
        """
        IBIT_TVC phase from actuation.c:
        Circular/square pattern using cos/sin with radial scaling.

        From firmware:
          0-25%:   radial lerp 0->1
          25-75%:  square pattern (1/cos or 1/sin at different angle ranges)
          75-100%: radial lerp 1->0
        Nest coefficient: 0.60.
        """
        dt = 0.01
        elapsed = 0.0
        nest = self._active_params.get('USE_NEST', 0) == 0
        coeff = IBIT_NEST_COEFFS['tvc'] if nest else 1.0
        max_cdeg = SERVO_HARD_LIMITS['tvc']

        if not self.ibit_pass:
            with self._lock:
                for flag, sname in MistrackingFlags.FLAG_TO_SURFACE.items():
                    if (self.mist_flags & flag) and 'tvc' in sname:
                        self.servos[sname].freeze()

        while elapsed < dur:
            with self._lock:
                if self.act_state != ActuationState.IBIT:
                    return
                pct = elapsed / dur
                angle = math.pi * 4 * pct

                # Radial scaling (from firmware)
                if pct <= 0.25:
                    radial = pct * 4.0
                elif pct < 0.3125:
                    radial = -1.0 / math.cos(angle) if math.cos(angle) != 0 else 1.0
                elif pct < 0.4375:
                    radial = -1.0 / math.sin(angle) if math.sin(angle) != 0 else 1.0
                elif pct < 0.5625:
                    radial = 1.0 / math.cos(angle) if math.cos(angle) != 0 else 1.0
                elif pct < 0.6875:
                    radial = 1.0 / math.sin(angle) if math.sin(angle) != 0 else 1.0
                elif pct < 0.75:
                    radial = -1.0 / math.cos(angle) if math.cos(angle) != 0 else 1.0
                else:
                    radial = (1.0 - pct) * 4.0

                radial *= coeff
                # Clamp -- ControlAllocation limits the output
                radial = max(-1.0, min(1.0, radial))

                roll_cmd = radial * math.cos(angle) * max_cdeg * 0.3
                pitch_cmd = radial * math.sin(angle) * max_cdeg * 0.3

                # TVC mapping: roll/pitch -> individual servos
                # Approximation of ControlAllocation output
                self.servos['left_tvc_upper'].cmd = (pitch_cmd + roll_cmd) * 0.5
                self.servos['left_tvc_lower'].cmd = (pitch_cmd - roll_cmd) * 0.5
                self.servos['right_tvc_upper'].cmd = (pitch_cmd - roll_cmd) * 0.5
                self.servos['right_tvc_lower'].cmd = (pitch_cmd + roll_cmd) * 0.5

            time.sleep(dt)
            elapsed += dt

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
                    # Servos are powered -- step dynamics with coupling
                    elev_load = abs(self.servos['left_elevon'].fb) + abs(self.servos['right_elevon'].fb)
                    for sname, servo in self.servos.items():
                        coupling = elev_load * 0.01 if 'rudder' in sname else 0.0
                        servo.step(dt, now, coupling)
                else:
                    # OFF mode: servos unpowered, feedback drifts to trim
                    for servo in self.servos.values():
                        servo.fb += (servo._trim_offset - servo.fb) * 0.1 * dt
                        servo.cur = random.gauss(5, 2)  # quiescent ~5mA
                        servo.vel = 0.0

                isub = self.ibit_substate
                imon = self.ibit_mon_status
                svs = self.servos

            drop = random.random() < self.drop_rate

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
                    s, sg, o = self.monitors.get_state()
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
                    s, _, _ = self.monitors.get_state()
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
