# -*- coding: utf-8 -*-
"""
PandionVehicleSim -- Real UDP MAVLink vehicle simulator.

Listens on a UDP port and responds with authentic Pandion MAVLink telemetry,
driving the full state machine:

  DISARMED → ARM → GROUND_ARMED → OPERATE → PLAYBACK → IBIT → OPERATE → DISARM

Configurable:
  - ibit_pass:       True  → IBIT completes with all surfaces passing
                     False → IBIT fails with configurable mistracking flags
  - monitors:        list of monitor IDs to assert on boot (simulates real faults)
  - ibit_duration_s: how long to spend in each IBIT substate
  - verbose:         print every sent/received message

Usage (one sim per vehicle):
    python -m sim.vehicle --port 9985 --sysid 1 --pass
    python -m sim.vehicle --port 9986 --sysid 2 --fail --mistracking 64,128
"""

import os
import sys
import time
import math
import random
import threading
import argparse

# Force UTF-8 output on Windows
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from pymavlink import mavutil

# Add dialect directory so pymavlink can find the pre-generated .py dialect
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
_DIALECT_DIR = os.path.join(_PROJECT_ROOT, "vehicle", "dialects")
if _DIALECT_DIR not in sys.path:
    sys.path.insert(0, _DIALECT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Pre-import the dialect module and inject it into pymavlink's namespace
# so mavutil.mavlink_connection(dialect=...) finds it without re-generating from XML
import importlib
_dialect = importlib.import_module("pandion_vehicle_roadrunner")
sys.modules["pymavlink.dialects.v10.pandion_vehicle_roadrunner"] = _dialect

import pymavlink.dialects.v10 as _v10_pkg
setattr(_v10_pkg, "pandion_vehicle_roadrunner", _dialect)

from pymavlink import mavutil


# ── State machine constants ────────────────────────────────────────────────────

class FlightRegime:
    GROUND_DISARMED = 0
    GROUND_ARMED    = 1
    AUTO_TAKEOFF    = 2
    HOVER           = 3
    FORWARD_TRANS   = 4
    CRUISE          = 5
    INVALID         = 255

class ActuationState:
    OFF      = 0
    IBIT     = 1
    OPERATE  = 2
    MANUAL   = 3
    PLAYBACK = 4
    TRIM     = 5

class IBITSubstate:
    BEGIN          = 0
    WAIT_FOR_SETTLE= 1
    ELEVON         = 2
    RUDDERS        = 3
    TVC            = 4
    COMPLETE       = 5

class MistrackingFlags:
    UPPER_RUDDER    = 1
    LOWER_RUDDER    = 2
    LEFT_TVC_UPPER  = 4
    LEFT_TVC_LOWER  = 8
    RIGHT_TVC_UPPER = 16
    RIGHT_TVC_LOWER = 32
    LEFT_ELEVON     = 64
    RIGHT_ELEVON    = 128

# IBIT substate timing (seconds per phase)
IBIT_PHASE_DURATIONS = {
    IBITSubstate.BEGIN:           1.0,
    IBITSubstate.WAIT_FOR_SETTLE: 3.0,
    IBITSubstate.ELEVON:          8.0,
    IBITSubstate.RUDDERS:         8.0,
    IBITSubstate.TVC:             8.0,
    IBITSubstate.COMPLETE:        2.0,
}


# ── Surface telemetry model ────────────────────────────────────────────────────

class SurfaceModel:
    """
    Simple first-order lag model for a servo surface.
    feedback tracks command with realistic lag and noise.
    """
    def __init__(self, initial_cdeg=0.0, tau=0.08, noise_cdeg=2.0):
        self.command_cdeg  = initial_cdeg
        self.feedback_cdeg = initial_cdeg
        self.tau           = tau          # time constant (s)
        self.noise_cdeg    = noise_cdeg
        self.current_mA    = 0.0
        self.temp_degC     = 25.0

    def step(self, dt):
        # First-order lag
        error = self.command_cdeg - self.feedback_cdeg
        self.feedback_cdeg += (error / self.tau) * dt
        # Noise
        self.feedback_cdeg += random.gauss(0, self.noise_cdeg * dt)
        # Current proportional to effort
        self.current_mA = abs(error) * 2.5 + random.gauss(200, 10)
        # Temperature creep
        self.temp_degC  = 25.0 + abs(self.command_cdeg) * 0.02


# ── Main simulator ─────────────────────────────────────────────────────────────

class PandionVehicleSim:
    """
    Full Pandion vehicle simulator.
    Sends real UDP MAVLink packets and reacts to commands from the test software.
    """

    def __init__(self,
                 bind_ip='0.0.0.0',
                 port=9985,
                 sysid=1,
                 ibit_pass=True,
                 mistracking_flags=0,
                 boot_monitors=None,
                 ibit_duration_scale=1.0,
                 verbose=False):
        """
        Args:
            bind_ip:              IP to bind UDP socket on
            port:                 UDP port (same as UUT ip:port in test software)
            sysid:                MAVLink system ID for this simulated vehicle
            ibit_pass:            True → IBIT passes, False → IBIT fails
            mistracking_flags:    Bitmask of surfaces that fail (used when ibit_pass=False)
            boot_monitors:        List of monitor IDs to assert on boot
            ibit_duration_scale:  Speed up (<1) or slow down (>1) IBIT phases
            verbose:              Print every message
        """
        self.bind_ip            = bind_ip
        self.port               = port
        self.sysid              = sysid
        self.ibit_pass          = ibit_pass
        self.mistracking_flags  = mistracking_flags if not ibit_pass else 0
        self.boot_monitors      = boot_monitors or [0, 1, 2, 3, 4, 5]  # typical set
        self.ibit_duration_scale= ibit_duration_scale
        self.verbose            = verbose

        # ── Vehicle state ──────────────────────────────────────────────
        self.flight_regime      = FlightRegime.GROUND_DISARMED
        self.actuation_state    = ActuationState.OFF
        self.ibit_substate      = IBITSubstate.BEGIN
        self.actuation_ibit_mon_status = 0  # mistracking flags, 0 = all pass

        # Parameters
        self.use_nest           = 0
        self.classic_mode_en    = 0
        self.stbl_prms_appvd    = 0

        # Monitor state (64 bytes = 512 monitor bits)
        self._set_monitors      = set(self.boot_monitors)
        self._overriding_monitors = set()
        self._setting_monitors  = set()

        # Surfaces
        self.surfaces = {
            'left_elevon':    SurfaceModel(),
            'right_elevon':   SurfaceModel(),
            'dorsal_rudder':  SurfaceModel(),
            'ventral_rudder': SurfaceModel(),
            'left_tvc_upper': SurfaceModel(),
            'left_tvc_lower': SurfaceModel(),
            'right_tvc_upper':SurfaceModel(),
            'right_tvc_lower':SurfaceModel(),
        }

        # ── MAVLink connection ─────────────────────────────────────────
        self.conn           = None
        self.gcs_addr       = None  # (ip, port) of GCS once we see a heartbeat
        self._running       = False
        self._lock          = threading.Lock()

        # Telemetry rate control
        self._last_hb_time    = 0
        self._last_telem_time = 0
        self._last_status_time= 0
        self._last_monitor_time=0
        self._dt              = 0.02  # 50 Hz sim tick

        print(f"[SIM:{self.sysid}] Pandion Vehicle Simulator")
        print(f"[SIM:{self.sysid}]   Port:      {self.port}")
        print(f"[SIM:{self.sysid}]   IBIT:      {'PASS' if ibit_pass else 'FAIL'}")
        if not ibit_pass:
            print(f"[SIM:{self.sysid}]   Mistracking: 0x{mistracking_flags:02X}")
        print(f"[SIM:{self.sysid}]   Monitors:  {self.boot_monitors}")

    # ── Start / stop ──────────────────────────────────────────────────────────

    def start(self):
        """Start the simulator (blocking). Call from main thread."""
        # The sim acts exactly like a real vehicle:
        #   - Sends telemetry TO the GCS port using udpout
        #   - pymavlink automatically receives replies on the same socket
        #   - No patches to production connect_to_vehicle needed
        #
        # The test software uses udpin:127.0.0.1:PORT which binds on PORT.
        # We use udpout:127.0.0.1:PORT which sends TO that PORT.
        # pymavlink's UDP socket is bidirectional — commands sent by the GCS
        # come back to our source (ephemeral) port on the same socket.
        connection_string = f"udpout:127.0.0.1:{self.port}"
        print(f"[SIM:{self.sysid}] Sending telemetry to {connection_string}")

        self.conn = mavutil.mavlink_connection(
            connection_string,
            dialect="pandion_vehicle_roadrunner",
            source_system=self.sysid,
            source_component=1,
        )
        self._running = True

        # Telemetry sender in background thread
        telem_thread = threading.Thread(target=self._telemetry_loop, daemon=True)
        telem_thread.start()

        # Main receive loop
        try:
            self._receive_loop()
        except KeyboardInterrupt:
            print(f"\n[SIM:{self.sysid}] Stopped.")
        finally:
            self._running = False

    def stop(self):
        self._running = False

    # ── Receive loop ──────────────────────────────────────────────────────────

    def _receive_loop(self):
        while self._running:
            msg = self.conn.recv_match(blocking=True, timeout=0.1)
            if msg is None:
                continue

            msg_type = msg.get_type()

            # Track GCS address from any received packet
            if hasattr(self.conn, 'last_address') and self.conn.last_address:
                self.gcs_addr = self.conn.last_address

            if self.verbose:
                print(f"[SIM:{self.sysid}] RX {msg_type}")

            if msg_type == 'HEARTBEAT':
                self._on_heartbeat(msg)
            elif msg_type == 'COMMAND_LONG':
                self._on_command_long(msg)
            elif msg_type == 'PARAM_REQUEST_READ':
                self._on_param_request_read(msg)
            elif msg_type == 'PARAM_SET':
                self._on_param_set(msg)
            elif msg_type == 'PANDION_RR_ACTUATION_REQUEST_MODE':
                self._on_actuation_request_mode(msg)
            elif msg_type == 'PANDION_MONITOR_OVERRIDE_CMD':
                self._on_monitor_override_cmd(msg)
            elif msg_type == 'PANDION_RR_PLAYBACK_COMMAND':
                self._on_playback_command(msg)

    # ── Telemetry loop ────────────────────────────────────────────────────────

    def _telemetry_loop(self):
        """Send periodic telemetry at realistic rates."""
        while self._running:
            now = time.time()
            dt  = self._dt

            # Step surface models
            with self._lock:
                for s in self.surfaces.values():
                    s.step(dt)

            # 1 Hz heartbeat
            if now - self._last_hb_time >= 1.0:
                self._send_heartbeat()
                self._last_hb_time = now

            # 10 Hz PANDION_STATUS
            if now - self._last_status_time >= 0.1:
                self._send_pandion_status()
                self._last_status_time = now

            # 20 Hz PANDION_RR_ACTUATION_SYS_STATUS
            if now - self._last_telem_time >= 0.05:
                self._send_actuation_sys_status()
                self._last_telem_time = now

            # 5 Hz monitor status
            if now - self._last_monitor_time >= 0.2:
                self._send_monitor_status()
                self._last_monitor_time = now

            time.sleep(dt)

    # ── Message handlers ──────────────────────────────────────────────────────

    def _on_heartbeat(self, msg):
        # Record GCS
        if self.verbose:
            print(f"[SIM:{self.sysid}] GCS heartbeat from sysid={msg.get_srcSystem()}")

    def _on_command_long(self, msg):
        if msg.command == 400:  # MAV_CMD_COMPONENT_ARM_DISARM
            arm = int(msg.param1)
            self._handle_arm_disarm(arm)

    def _handle_arm_disarm(self, arm):
        with self._lock:
            if arm == 1:
                # Check monitors — only ARM if no monitors set
                if self._set_monitors:
                    result = 1  # TEMPORARILY_REJECTED
                    if self.verbose:
                        print(f"[SIM:{self.sysid}] ARM rejected — monitors SET: {self._set_monitors}")
                else:
                    self.flight_regime   = FlightRegime.GROUND_ARMED
                    self.actuation_state = ActuationState.OPERATE
                    result = 0  # ACCEPTED
                    print(f"[SIM:{self.sysid}] ARMED → OPERATE")
            else:
                self.flight_regime   = FlightRegime.GROUND_DISARMED
                self.actuation_state = ActuationState.OFF
                result = 0
                print(f"[SIM:{self.sysid}] DISARMED → OFF")

        self.conn.mav.command_ack_send(400, result)

    def _on_param_request_read(self, msg):
        if isinstance(msg.param_id, bytes):
            name = msg.param_id.decode('utf-8').rstrip('\x00')
        else:
            name = str(msg.param_id).rstrip('\x00')

        param_map = {
            'USE_NEST':        float(self.use_nest),
            'CLASSIC_MODE_EN': float(self.classic_mode_en),
            'STBL_PRMS_APPVD': float(self.stbl_prms_appvd),
        }

        if name in param_map:
            self._send_param_value(name, param_map[name])
        else:
            # Unknown param — return 0
            self._send_param_value(name, 0.0)

    def _on_param_set(self, msg):
        if isinstance(msg.param_id, bytes):
            name = msg.param_id.decode('utf-8').rstrip('\x00')
        else:
            name = str(msg.param_id).rstrip('\x00')

        val = int(msg.param_value)
        with self._lock:
            if name == 'USE_NEST':
                self.use_nest = val
            elif name == 'CLASSIC_MODE_EN':
                self.classic_mode_en = val
            elif name == 'STBL_PRMS_APPVD':
                self.stbl_prms_appvd = val

        print(f"[SIM:{self.sysid}] PARAM_SET {name} = {val}")
        self._send_param_value(name, float(val))

    def _on_actuation_request_mode(self, msg):
        requested = msg.requested_mode
        mode_names = {0:"OFF", 1:"IBIT", 2:"OPERATE", 3:"MANUAL", 4:"PLAYBACK", 5:"TRIM"}

        with self._lock:
            current = self.actuation_state

        print(f"[SIM:{self.sysid}] Mode request: {mode_names.get(current,'?')} → {mode_names.get(requested,'?')}")

        # Validate transitions
        valid = False
        if requested == ActuationState.PLAYBACK and current == ActuationState.OPERATE:
            valid = True
        elif requested == ActuationState.IBIT and current == ActuationState.PLAYBACK:
            valid = True
        elif requested == ActuationState.OPERATE and current in (
            ActuationState.IBIT, ActuationState.PLAYBACK, ActuationState.MANUAL
        ):
            valid = True
        elif requested == ActuationState.OFF:
            valid = True
        elif requested == ActuationState.OPERATE and current == ActuationState.OFF:
            valid = False  # Must ARM first

        if valid:
            with self._lock:
                old_state = self.actuation_state
                self.actuation_state = requested
                if requested == ActuationState.IBIT:
                    # Start IBIT state machine in background
                    ibit_thread = threading.Thread(
                        target=self._run_ibit_sequence, daemon=True
                    )
                    ibit_thread.start()
            print(f"[SIM:{self.sysid}]   → {mode_names.get(requested,'?')} accepted")
        else:
            print(f"[SIM:{self.sysid}]   → REJECTED (invalid transition)")

    def _on_monitor_override_cmd(self, msg):
        """
        Handle PANDION_MONITOR_OVERRIDE_CMD.
        override_cmd: 0=CANCEL, 1=SET, 2=CLEAR
        """
        cmd       = msg.override_cmd
        monitor_id= msg.monitor_id

        with self._lock:
            if cmd == 2:  # CLEAR
                self._set_monitors.discard(monitor_id)
                self._overriding_monitors.add(monitor_id)
                if self.verbose:
                    print(f"[SIM:{self.sysid}] Monitor {monitor_id} CLEARED")
            elif cmd == 0:  # CANCEL override
                self._overriding_monitors.discard(monitor_id)
            elif cmd == 1:  # SET (force)
                self._set_monitors.add(monitor_id)

    def _on_playback_command(self, msg):
        """Accept playback commands and apply to surface models."""
        with self._lock:
            self.surfaces['left_elevon'].command_cdeg    = msg.left_elevon_ted_command_cdeg
            self.surfaces['right_elevon'].command_cdeg   = msg.right_elevon_ted_command_cdeg
            self.surfaces['dorsal_rudder'].command_cdeg  = msg.upper_rudder_tel_command_cdeg
            self.surfaces['ventral_rudder'].command_cdeg = msg.lower_rudder_tel_command_cdeg
            self.surfaces['left_tvc_upper'].command_cdeg = msg.left_tvc_upper_command_cdeg
            self.surfaces['left_tvc_lower'].command_cdeg = msg.left_tvc_lower_command_cdeg
            self.surfaces['right_tvc_upper'].command_cdeg= msg.right_tvc_upper_command_cdeg
            self.surfaces['right_tvc_lower'].command_cdeg= msg.right_tvc_lower_command_cdeg

    # ── IBIT state machine ────────────────────────────────────────────────────

    def _run_ibit_sequence(self):
        """Run through IBIT substates and command surfaces appropriately."""
        print(f"[SIM:{self.sysid}] IBIT sequence starting...")
        substates = [
            IBITSubstate.BEGIN,
            IBITSubstate.WAIT_FOR_SETTLE,
            IBITSubstate.ELEVON,
            IBITSubstate.RUDDERS,
            IBITSubstate.TVC,
            IBITSubstate.COMPLETE,
        ]

        # IBIT surface command profiles (cdeg)
        ibit_commands = {
            IBITSubstate.ELEVON:  {
                'left_elevon':  1500, 'right_elevon': -1500
            },
            IBITSubstate.RUDDERS: {
                'dorsal_rudder': 1200, 'ventral_rudder': -1200
            },
            IBITSubstate.TVC: {
                'left_tvc_upper': 800, 'left_tvc_lower': -800,
                'right_tvc_upper': 800, 'right_tvc_lower': -800
            },
        }

        # Reset all surfaces to neutral
        with self._lock:
            self.actuation_ibit_mon_status = 0
            for s in self.surfaces.values():
                s.command_cdeg = 0.0

        for substate in substates:
            with self._lock:
                if self.actuation_state != ActuationState.IBIT:
                    print(f"[SIM:{self.sysid}] IBIT aborted (mode changed)")
                    return
                self.ibit_substate = substate

            substate_names = {0:"BEGIN", 1:"SETTLE", 2:"ELEVON", 3:"RUDDERS", 4:"TVC", 5:"COMPLETE"}
            print(f"[SIM:{self.sysid}] IBIT substate: {substate_names.get(substate,'?')}")

            # Apply surface commands for this phase
            cmds = ibit_commands.get(substate, {})
            with self._lock:
                for surf_name, cdeg in cmds.items():
                    self.surfaces[surf_name].command_cdeg = cdeg

            # If failing, inject mistracking: add noise to prevent tracking
            if not self.ibit_pass and substate in (
                IBITSubstate.ELEVON, IBITSubstate.RUDDERS, IBITSubstate.TVC
            ):
                self._inject_mistracking(substate)

            duration = IBIT_PHASE_DURATIONS[substate] * self.ibit_duration_scale
            time.sleep(duration)

        # Set final mistracking status
        with self._lock:
            if not self.ibit_pass:
                self.actuation_ibit_mon_status = self.mistracking_flags
            else:
                self.actuation_ibit_mon_status = 0

            # IBIT complete — transition back to OPERATE
            self.actuation_state = ActuationState.OPERATE
            self.ibit_substate   = IBITSubstate.COMPLETE

            # Return surfaces to neutral
            for s in self.surfaces.values():
                s.command_cdeg = 0.0

        result = "PASS" if self.ibit_pass else f"FAIL (flags=0x{self.mistracking_flags:02X})"
        print(f"[SIM:{self.sysid}] IBIT complete → OPERATE  [{result}]")

    def _inject_mistracking(self, substate):
        """Inject tracking error on surfaces that should fail."""
        flag_to_surface = {
            MistrackingFlags.LEFT_ELEVON:    'left_elevon',
            MistrackingFlags.RIGHT_ELEVON:   'right_elevon',
            MistrackingFlags.UPPER_RUDDER:   'dorsal_rudder',
            MistrackingFlags.LOWER_RUDDER:   'ventral_rudder',
            MistrackingFlags.LEFT_TVC_UPPER: 'left_tvc_upper',
            MistrackingFlags.LEFT_TVC_LOWER: 'left_tvc_lower',
            MistrackingFlags.RIGHT_TVC_UPPER:'right_tvc_upper',
            MistrackingFlags.RIGHT_TVC_LOWER:'right_tvc_lower',
        }
        with self._lock:
            for flag, surf_name in flag_to_surface.items():
                if self.mistracking_flags & flag:
                    # Freeze feedback far from command to simulate mistracking
                    surf = self.surfaces[surf_name]
                    surf.feedback_cdeg = surf.command_cdeg + 200.0  # >50 counts off

    # ── Telemetry senders ─────────────────────────────────────────────────────

    def _send_heartbeat(self):
        self.conn.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_FIXED_WING,
            mavutil.mavlink.MAV_AUTOPILOT_GENERIC,
            0, 0,
            mavutil.mavlink.MAV_STATE_ACTIVE
        )

    def _send_pandion_status(self):
        with self._lock:
            regime = self.flight_regime
        try:
            self.conn.mav.pandion_status_send(
                flight_regime=regime,
                contingency_level=0,
                contingency_reason=0,
                mission_type=0,
                imu_health=1,
                nav_solution_valid=1,
                time_since_last_valid_gps_s=0,
                time_since_last_valid_baro_s=0,
                time_since_last_valid_mag_s=0,
                time_since_last_valid_pitot_s=0,
                time_since_last_valid_gps_vel_s=0,
            )
        except Exception:
            pass

    def _send_actuation_sys_status(self):
        with self._lock:
            mode     = self.actuation_state
            substate = self.ibit_substate
            mon_status = self.actuation_ibit_mon_status
            s = self.surfaces

            # Build field values
            def fb(surf): return int(s[surf].feedback_cdeg)
            def curr(surf): return int(s[surf].current_mA)
            def temp(surf): return int(s[surf].temp_degC)

        try:
            self.conn.mav.pandion_rr_actuation_sys_status_send(
                actuation_state=mode,
                actuation_ibit_substate=substate,
                actuation_ibit_mon_status=mon_status,

                left_elevon_feedback_cdeg=fb('left_elevon'),
                right_elevon_feedback_cdeg=fb('right_elevon'),
                dorsal_rudder_feedback_cdeg=fb('dorsal_rudder'),
                ventral_rudder_feedback_cdeg=fb('ventral_rudder'),
                left_tvc_upper_feedback_cdeg=fb('left_tvc_upper'),
                left_tvc_lower_feedback_cdeg=fb('left_tvc_lower'),
                right_tvc_upper_feedback_cdeg=fb('right_tvc_upper'),
                right_tvc_lower_feedback_cdeg=fb('right_tvc_lower'),

                left_elevon_current_mA=curr('left_elevon'),
                right_elevon_current_mA=curr('right_elevon'),
                dorsal_rudder_current_mA=curr('dorsal_rudder'),
                ventral_rudder_current_mA=curr('ventral_rudder'),
                left_tvc_upper_current_mA=curr('left_tvc_upper'),
                left_tvc_lower_current_mA=curr('left_tvc_lower'),
                right_tvc_upper_current_mA=curr('right_tvc_upper'),
                right_tvc_lower_current_mA=curr('right_tvc_lower'),

                left_elevon_motor_temp_degC=temp('left_elevon'),
                right_elevon_motor_temp_degC=temp('right_elevon'),
            )
        except Exception:
            pass

    def _send_monitor_status(self):
        """Send PANDION_MONITOR_CURRENT_STATUS with current monitor bits."""
        # Build 64-byte arrays
        currently_set      = bytearray(64)
        currently_setting  = bytearray(64)
        currently_overridden = bytearray(64)

        with self._lock:
            for mid in self._set_monitors:
                if 0 <= mid < 512:
                    currently_set[mid // 8] |= (1 << (mid % 8))
            for mid in self._setting_monitors:
                if 0 <= mid < 512:
                    currently_setting[mid // 8] |= (1 << (mid % 8))
            for mid in self._overriding_monitors:
                if 0 <= mid < 512:
                    currently_overridden[mid // 8] |= (1 << (mid % 8))

        try:
            self.conn.mav.pandion_monitor_current_status_send(
                currently_set=bytes(currently_set),
                currently_setting=bytes(currently_setting),
                currently_overridden=bytes(currently_overridden),
            )
        except Exception:
            pass

    def _send_param_value(self, name, value):
        param_id = name.encode('utf-8') + b'\x00' * (16 - len(name))
        try:
            self.conn.mav.param_value_send(
                param_id=param_id,
                param_value=value,
                param_type=9,   # MAV_PARAM_TYPE_UINT8
                param_count=10,
                param_index=0,
            )
        except Exception:
            pass
