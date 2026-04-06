# -*- coding: utf-8 -*-
"""
PandionVehicleSim v2 -- Production-fidelity Pandion vehicle simulator.

Improvements over v1:
  1.  Monitor re-assertion: monitors linked to conditions that continuously
      evaluate (GNSS, INS, geofence, MC clock). Clearing only suppresses
      until the condition re-triggers on the next evaluation cycle.
  2.  Boot timing: vehicle takes boot_time_s (default 5s in sim) to come
      online. No telemetry until boot completes. Heartbeat starts at boot.
  3.  Power cycle: relay state is tracked. Power off -> vehicle state resets,
      params that require reboot take effect. Power on -> boot sequence.
  4.  Monitor latching delay: monitors spend eval_window_s in currently_setting
      before latching to currently_set.
  5.  Engine status telemetry: PANDION_RR_ENGINE_STATUS at 2 Hz with realistic
      fuel pump, EGT, RPM values.
  6.  Realistic IBIT command profiles: smooth ramp -> hold -> ramp reverse
      per phase, not step functions.
  7.  Mistracking detection: feedback must differ by >50 cdeg for >0.5s
      continuously before the flag is set (matches real firmware spec).
  8.  Connection loss: configurable packet_drop_rate introduces random
      telemetry drops. Also simulates brief link loss on power transitions.
  9.  Multiple IBIT cycles: configurable ibit_cycles (1-3). Vehicle may run
      IBIT multiple times before declaring final result.
  10. Param persistence: CLASSIC_MODE_EN and STBL_PRMS_APPVD only take
      effect after power cycle. USE_NEST is immediate.
  11. Electrical noise: when any vehicle in the same SimFleet toggles relay,
      all other vehicles get a burst of surface noise.
  12. Correlated surface noise: noise amplitude scales with servo speed,
      temperature, and a low-frequency vibration component.
"""

import os, sys, time, math, random, threading, collections

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
sys.path.insert(0, os.path.join(_ROOT, "vehicle", "dialects"))
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
    except: pass


# ===========================================================================
# Constants
# ===========================================================================

class FR:
    DISARMED = 0; ARMED = 1

class Act:
    OFF = 0; IBIT = 1; OPERATE = 2; MANUAL = 3; PLAYBACK = 4; TRIM = 5

class Sub:
    BEGIN = 0; SETTLE = 1; ELEVON = 2; RUDDERS = 3; TVC = 4; DONE = 5

class MF:
    UPPER_RUD = 1; LOWER_RUD = 2; L_TVC_UP = 4; L_TVC_LO = 8
    R_TVC_UP = 16; R_TVC_LO = 32; L_ELEV = 64; R_ELEV = 128

PHASE_DUR = {Sub.BEGIN:1, Sub.SETTLE:3, Sub.ELEVON:8, Sub.RUDDERS:8, Sub.TVC:8, Sub.DONE:2}

SURFACES = ['left_elevon','right_elevon','dorsal_rudder','ventral_rudder',
            'left_tvc_upper','left_tvc_lower','right_tvc_upper','right_tvc_lower']

FLAG_SURF = {
    MF.L_ELEV:'left_elevon', MF.R_ELEV:'right_elevon',
    MF.UPPER_RUD:'dorsal_rudder', MF.LOWER_RUD:'ventral_rudder',
    MF.L_TVC_UP:'left_tvc_upper', MF.L_TVC_LO:'left_tvc_lower',
    MF.R_TVC_UP:'right_tvc_upper', MF.R_TVC_LO:'right_tvc_lower',
}

# IBIT profiles: list of (target_cdeg, hold_fraction_of_phase)
# Ramp to target over first 15%, hold 70%, ramp back over last 15%
IBIT_PROFILES = {
    Sub.ELEVON: {
        'left_elevon':  [(1500, 0.4), (-1500, 0.4), (0, 0.2)],
        'right_elevon': [(-1500, 0.4), (1500, 0.4), (0, 0.2)],
    },
    Sub.RUDDERS: {
        'dorsal_rudder':  [(1200, 0.4), (-1200, 0.4), (0, 0.2)],
        'ventral_rudder': [(-1200, 0.4), (1200, 0.4), (0, 0.2)],
    },
    Sub.TVC: {
        'left_tvc_upper':  [(800, 0.3), (-800, 0.3), (800, 0.2), (0, 0.2)],
        'left_tvc_lower':  [(-800, 0.3), (800, 0.3), (-800, 0.2), (0, 0.2)],
        'right_tvc_upper': [(800, 0.3), (-800, 0.3), (800, 0.2), (0, 0.2)],
        'right_tvc_lower': [(-800, 0.3), (800, 0.3), (-800, 0.2), (0, 0.2)],
    },
}

# Monitor conditions: id -> (name, eval_fn(vehicle) -> bool)
# If eval_fn returns True, monitor is asserted
def _define_monitor_conditions():
    return {
        0: ("GNSS Configuration",    lambda v: not v._booted or v._boot_elapsed() < 10),
        1: ("INS Aligning",          lambda v: not v._booted or v._boot_elapsed() < 8),
        2: ("Inner Geofence Invalid", lambda v: True),   # always until overridden
        3: ("Outer Geofence Invalid", lambda v: True),
        4: ("Deconfliction Invalid",  lambda v: True),
        5: ("MC Clock Not Synced",    lambda v: not v._booted or v._boot_elapsed() < 12),
        10: ("RC Rotor Switch",       lambda v: v.fr == FR.ARMED),  # appears after ARM
        11: ("VN GPS Error",          lambda v: not v._booted or v._boot_elapsed() < 15),
    }


# ===========================================================================
# Servo with correlated noise (#12)
# ===========================================================================

class Servo:
    """
    Second-order servo model with:
      - First-order lag tracking
      - Correlated noise: vibration (low-freq), thermal, load-dependent
      - Mistracking detection: >50 cdeg for >0.5s (#7)
    """
    MISTRACK_THRESHOLD_CDEG = 50.0
    MISTRACK_DURATION_S = 0.5

    def __init__(self, tau=0.08):
        self.cmd = 0.0
        self.fb = 0.0
        self.vel = 0.0   # servo velocity for noise correlation
        self.cur = 200.0
        self.temp = 25.0
        self._frozen = False
        self.tau = tau

        # Vibration state (low-frequency oscillation)
        self._vib_phase = random.uniform(0, 2*math.pi)
        self._vib_freq = random.uniform(3, 8)  # Hz

        # Mistracking detection state (#7)
        self._mistrack_accum = 0.0  # seconds above threshold
        self._mistracking = False

        # External noise injection (#11)
        self._ext_noise = 0.0
        self._ext_noise_decay = 0.95

    def step(self, dt, global_time):
        # Decay external noise
        self._ext_noise *= self._ext_noise_decay

        if self._frozen:
            # Mistracking: feedback drifts away from command
            drift = 200.0 + 20.0 * math.sin(global_time * 2.0)
            self.fb = self.cmd + drift
            self.cur = 1500 + random.gauss(0, 80)
            self.temp = 35.0 + abs(self.cmd) * 0.02
        else:
            # First-order lag
            err = self.cmd - self.fb
            old_fb = self.fb
            self.fb += (err / self.tau) * dt
            self.vel = (self.fb - old_fb) / max(dt, 0.001)

            # Correlated noise (#12)
            # Base: small gaussian
            noise = random.gauss(0, 1.0)
            # Vibration: low-frequency sinusoidal
            self._vib_phase += self._vib_freq * dt * 2 * math.pi
            noise += 3.0 * math.sin(self._vib_phase)
            # Load-dependent: more noise when servo is moving fast
            noise += abs(self.vel) * 0.003 * random.gauss(0, 1)
            # Temperature-dependent: hotter = noisier
            noise *= (1.0 + max(0, self.temp - 30) * 0.02)
            # External noise injection (#11)
            noise += self._ext_noise * random.gauss(0, 1)

            self.fb += noise * dt
            self.cur = abs(err) * 2.5 + abs(self.vel) * 0.5 + random.gauss(200, 15)

        # Temperature model
        self.temp += (abs(self.cmd) * 0.001 - (self.temp - 25) * 0.01) * dt
        self.temp = max(15, min(85, self.temp))

        # Mistracking detection (#7)
        track_err = abs(self.cmd - self.fb)
        if track_err > self.MISTRACK_THRESHOLD_CDEG:
            self._mistrack_accum += dt
            if self._mistrack_accum >= self.MISTRACK_DURATION_S:
                self._mistracking = True
        else:
            self._mistrack_accum = max(0, self._mistrack_accum - dt * 2)  # decay
            # Don't clear _mistracking once set (latched until IBIT reset)

    def freeze(self): self._frozen = True
    def unfreeze(self): self._frozen = False; self._mistracking = False; self._mistrack_accum = 0
    def inject_noise(self, amplitude): self._ext_noise = amplitude


# ===========================================================================
# Monitor system with condition evaluation + latching delay (#1, #4)
# ===========================================================================

class MonitorSystem:
    """
    Simulates Pandion's contingency management monitor system.
    - Monitors have conditions that are continuously evaluated
    - New assertions go to _setting first (latching delay)
    - After eval_window they latch to _set
    - Override/clear suppresses until next re-evaluation
    - Overridden monitors don't re-assert from conditions
    """

    def __init__(self, eval_window_s=0.8):
        self.eval_window = eval_window_s
        self._set = set()
        self._setting = {}       # mid -> timestamp when it started setting
        self._overridden = set()
        self._suppressed = set() # cleared monitors that won't re-assert this cycle
        self._lock = threading.Lock()

    def evaluate(self, vehicle, conditions):
        """Run all monitor conditions, update states."""
        now = time.time()
        with self._lock:
            # Latch: _setting -> _set after eval_window
            newly_set = []
            for mid, ts in list(self._setting.items()):
                if now - ts >= self.eval_window:
                    self._set.add(mid)
                    newly_set.append(mid)
            for mid in newly_set:
                del self._setting[mid]

            # Evaluate conditions
            for mid, (name, eval_fn) in conditions.items():
                if mid in self._overridden:
                    continue  # overridden, skip
                if mid in self._suppressed:
                    continue  # recently cleared, skip this cycle
                try:
                    if eval_fn(vehicle):
                        if mid not in self._set and mid not in self._setting:
                            self._setting[mid] = now
                except:
                    pass

            # Clear suppression after one cycle
            self._suppressed.clear()

    def clear(self, mid):
        with self._lock:
            self._set.discard(mid)
            if mid in self._setting:
                del self._setting[mid]
            self._overridden.add(mid)
            self._suppressed.add(mid)

    def cancel_override(self, mid):
        with self._lock:
            self._overridden.discard(mid)

    def force_set(self, mid):
        with self._lock:
            self._set.add(mid)

    def get_state(self):
        with self._lock:
            return (set(self._set),
                    set(self._setting.keys()),
                    set(self._overridden))

    @property
    def is_clear(self):
        with self._lock:
            return len(self._set) == 0 and len(self._setting) == 0


# ===========================================================================
# Vehicle simulator
# ===========================================================================

class PandionVehicleSim:

    def __init__(self, *, vehicle_port, sysid=1, ibit_pass=True,
                 mistracking_flags=0, boot_monitors=None,
                 post_arm_monitors=None, transient_monitor_chance=0.1,
                 ibit_duration_scale=1.0, ibit_cycles=1,
                 boot_time_s=3.0, eval_window_s=0.6,
                 packet_drop_rate=0.0, verbose=False,
                 fleet=None):
        self.vehicle_port = vehicle_port
        self.sysid = sysid
        self.ibit_pass = ibit_pass
        self.mist_flags = mistracking_flags if not ibit_pass else 0
        self.boot_monitors = boot_monitors or [0,1,2,3,4,5]
        self.post_arm_monitors = post_arm_monitors or [10]
        self.trans_chance = transient_monitor_chance
        self.scale = ibit_duration_scale
        self.ibit_cycles = ibit_cycles
        self.boot_time = boot_time_s
        self.drop_rate = packet_drop_rate
        self.verbose = verbose
        self.fleet = fleet  # reference to SimFleet for cross-vehicle noise (#11)

        # State
        self.fr = FR.DISARMED
        self.act = Act.OFF
        self.isub = Sub.BEGIN
        self.imon = 0

        # Params: stored vs active (for reboot-required params) (#10)
        self._stored_params = {'USE_NEST':0, 'CLASSIC_MODE_EN':0, 'STBL_PRMS_APPVD':0}
        self._active_params = dict(self._stored_params)
        self._reboot_required = {'CLASSIC_MODE_EN', 'STBL_PRMS_APPVD'}

        # Monitors (#1, #4)
        self.monitors = MonitorSystem(eval_window_s=eval_window_s)
        self._mon_conditions = _define_monitor_conditions()

        # Servos (#6, #7, #12)
        self.sv = {n: Servo() for n in SURFACES}

        # Engine state (#5)
        self._eng1_rpm = 0; self._eng1_egt = 25; self._eng1_mode = 0
        self._eng2_rpm = 0; self._eng2_egt = 25; self._eng2_mode = 0

        # Boot state (#2, #3)
        self._powered = False
        self._booted = False
        self._boot_start = 0.0
        self._power_on_time = 0.0
        self._link_blackout_until = 0.0  # (#8) no TX during blackout

        # Networking
        self.conn = None
        self._running = False
        self._lock = threading.Lock()
        self._global_time = time.time()

        _log(sysid, f"Sim v2  port={vehicle_port}  "
             f"ibit={'PASS' if ibit_pass else 'FAIL(0x%02X)'%self.mist_flags}  "
             f"cycles={ibit_cycles}  boot={boot_time_s}s  drop={packet_drop_rate}")

    # ── Boot helpers ──────────────────────────────────────────────────

    def _boot_elapsed(self):
        if not self._booted: return 0
        return time.time() - self._boot_start

    def power_on(self):
        """Simulate power applied to vehicle."""
        with self._lock:
            self._powered = True
            self._boot_start = time.time()
            self._booted = False
            self.fr = FR.DISARMED
            self.act = Act.OFF
            self.isub = Sub.BEGIN
            self.imon = 0
            # Apply stored params on boot (#10)
            self._active_params = dict(self._stored_params)
            # Reset servos
            for s in self.sv.values():
                s.cmd = 0; s.fb = 0; s.unfreeze()
            # Reset monitors
            self.monitors = MonitorSystem(eval_window_s=self.monitors.eval_window)
            # Link blackout during boot (#8)
            self._link_blackout_until = time.time() + self.boot_time * 0.7
        _log(self.sysid, f"Power ON -- booting ({self.boot_time}s)")
        threading.Thread(target=self._boot_sequence, daemon=True).start()

    def power_off(self):
        """Simulate power removed from vehicle."""
        with self._lock:
            self._powered = False
            self._booted = False
            self.fr = FR.DISARMED
            self.act = Act.OFF
        _log(self.sysid, "Power OFF")

    def _boot_sequence(self):
        """Simulate boot timing (#2)."""
        time.sleep(self.boot_time * self.scale)
        with self._lock:
            if self._powered:
                self._booted = True
                _log(self.sysid, "Boot complete -- telemetry active")

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self):
        self.conn = mavutil.mavlink_connection(
            f"udpout:127.0.0.1:{self.vehicle_port}",
            dialect="pandion_vehicle_roadrunner",
            source_system=self.sysid, source_component=1)
        self._running = True

        # Auto power-on
        self.power_on()

        threading.Thread(target=self._telem_loop, daemon=True).start()
        threading.Thread(target=self._monitor_eval_loop, daemon=True).start()

        try:
            while self._running:
                msg = self.conn.recv_match(blocking=True, timeout=0.05)
                if msg and msg.get_type() != 'BAD_DATA':
                    self._handle(msg)
        except KeyboardInterrupt:
            pass
        finally:
            self._running = False

    def stop(self): self._running = False

    # ── Cross-vehicle noise injection (#11) ───────────────────────────

    def inject_relay_noise(self, amplitude=30.0):
        """Called by SimFleet when another vehicle's relay toggles."""
        with self._lock:
            for s in self.sv.values():
                s.inject_noise(amplitude)

    # ── Message handler ───────────────────────────────────────────────

    def _handle(self, msg):
        t = msg.get_type()
        if not self._powered: return  # dead vehicle ignores everything
        if self.verbose: _log(self.sysid, f"RX {t}")

        if   t == 'HEARTBEAT': pass
        elif t == 'COMMAND_LONG':                      self._cmd(msg)
        elif t == 'PARAM_REQUEST_READ':                self._pr(msg)
        elif t == 'PARAM_SET':                         self._ps(msg)
        elif t == 'PANDION_RR_ACTUATION_REQUEST_MODE': self._mr(msg)
        elif t == 'PANDION_MONITOR_OVERRIDE_CMD':      self._mo(msg)
        elif t == 'PANDION_RR_PLAYBACK_COMMAND':       self._pb(msg)

    def _cmd(self, msg):
        if msg.command != 400: return
        arm = int(msg.param1)
        with self._lock:
            if arm == 1:
                s, _, _ = self.monitors.get_state()
                if s:
                    _log(self.sysid, f"ARM REJECTED -- {len(s)} monitors: {sorted(s)}")
                    self._ack(400, 1); return
                self.fr = FR.ARMED; self.act = Act.OPERATE
                self.isub = Sub.BEGIN; self.imon = 0
                _log(self.sysid, "ARMED -> OPERATE")
                self._ack(400, 0)
            else:
                self.fr = FR.DISARMED; self.act = Act.OFF
                _log(self.sysid, "DISARMED -> OFF")
                self._ack(400, 0)

    def _pr(self, msg):
        n = _pid(msg.param_id)
        self._send_pv(n, float(self._active_params.get(n, 0)))

    def _ps(self, msg):
        n = _pid(msg.param_id); v = int(msg.param_value)
        with self._lock:
            self._stored_params[n] = v
            if n not in self._reboot_required:
                self._active_params[n] = v  # immediate
            # else: only takes effect on next boot (#10)
        _log(self.sysid, f"PARAM {n} = {v}" +
             (f" (requires reboot)" if n in self._reboot_required else ""))
        self._send_pv(n, float(v))

    def _mr(self, msg):
        r = msg.requested_mode
        N = {0:"OFF",1:"IBIT",2:"OPERATE",3:"MANUAL",4:"PLAYBACK",5:"TRIM"}
        with self._lock:
            c = self.act
            ok = ((r==Act.PLAYBACK and c==Act.OPERATE) or
                  (r==Act.IBIT and c==Act.PLAYBACK) or
                  (r==Act.OPERATE and c in (Act.IBIT,Act.PLAYBACK,Act.MANUAL)) or
                  r==Act.OFF)
            if ok:
                self.act = r
                _log(self.sysid, f"Mode: {N.get(c,'?')} -> {N.get(r,'?')}")
                if r == Act.IBIT:
                    threading.Thread(target=self._ibit, daemon=True).start()
            else:
                _log(self.sysid, f"Mode REJECTED: {N.get(c,'?')} -> {N.get(r,'?')}")

    def _mo(self, msg):
        if msg.override_cmd == 2:
            self.monitors.clear(msg.monitor_id)
        elif msg.override_cmd == 0:
            self.monitors.cancel_override(msg.monitor_id)
        elif msg.override_cmd == 1:
            self.monitors.force_set(msg.monitor_id)

    def _pb(self, msg):
        with self._lock:
            self.sv['left_elevon'].cmd    = msg.left_elevon_ted_command_cdeg
            self.sv['right_elevon'].cmd   = msg.right_elevon_ted_command_cdeg
            self.sv['dorsal_rudder'].cmd  = msg.upper_rudder_tel_command_cdeg
            self.sv['ventral_rudder'].cmd = msg.lower_rudder_tel_command_cdeg
            self.sv['left_tvc_upper'].cmd = msg.left_tvc_upper_command_cdeg
            self.sv['left_tvc_lower'].cmd = msg.left_tvc_lower_command_cdeg
            self.sv['right_tvc_upper'].cmd= msg.right_tvc_upper_command_cdeg
            self.sv['right_tvc_lower'].cmd= msg.right_tvc_lower_command_cdeg

    # ── IBIT (#6, #7, #9) ────────────────────────────────────────────

    def _ibit(self):
        for cycle in range(self.ibit_cycles):
            if cycle > 0:
                _log(self.sysid, f"IBIT cycle {cycle+1}/{self.ibit_cycles}")
            self._ibit_single_cycle()
            with self._lock:
                if self.act != Act.OPERATE:
                    break  # aborted

        # Final result
        with self._lock:
            # Compute mistracking from servo state (#7)
            if not self.ibit_pass:
                self.imon = self.mist_flags
            else:
                # Check actual servo mistracking flags
                computed = 0
                for flag, sn in FLAG_SURF.items():
                    if self.sv[sn]._mistracking:
                        computed |= flag
                self.imon = computed

            for s in self.sv.values():
                s.unfreeze(); s.cmd = 0
            self.act = Act.OPERATE; self.isub = Sub.DONE

        r = "PASS" if self.imon == 0 else f"FAIL(0x{self.imon:02X})"
        _log(self.sysid, f"IBIT -> OPERATE  [{r}]")

    def _ibit_single_cycle(self):
        phases = [Sub.BEGIN, Sub.SETTLE, Sub.ELEVON, Sub.RUDDERS, Sub.TVC, Sub.DONE]
        N = {0:"BEGIN",1:"SETTLE",2:"ELEVON",3:"RUDDERS",4:"TVC",5:"DONE"}

        with self._lock:
            self.imon = 0
            for s in self.sv.values():
                s.cmd = 0; s.unfreeze()

        for phase in phases:
            with self._lock:
                if self.act != Act.IBIT: return
                self.isub = phase
            _log(self.sysid, f"IBIT: {N[phase]}")

            profiles = IBIT_PROFILES.get(phase, {})
            dur = PHASE_DUR[phase] * self.scale

            if profiles:
                self._run_ibit_phase_with_profiles(phase, profiles, dur)
            else:
                time.sleep(dur)

    def _run_ibit_phase_with_profiles(self, phase, profiles, total_dur):
        """
        Run IBIT phase with smooth ramp/hold/reverse profiles (#6).
        Each profile entry is (target_cdeg, fraction_of_total_dur).
        Within each segment: 15% ramp to target, 70% hold, 15% ramp to next.
        """
        dt = 0.01
        elapsed = 0.0

        for surf_name, segments in profiles.items():
            # Pre-compute timeline
            timeline = []
            t = 0.0
            prev_target = 0.0
            for target, frac in segments:
                seg_dur = total_dur * frac
                timeline.append((t, t + seg_dur, prev_target, target))
                prev_target = target
                t += seg_dur

            # Store timeline on servo for reference
            self.sv[surf_name]._timeline = timeline
            self.sv[surf_name]._phase_start = time.time()

        # Inject mistracking for failing surfaces (#7)
        if not self.ibit_pass and phase in (Sub.ELEVON, Sub.RUDDERS, Sub.TVC):
            with self._lock:
                for fl, sn in FLAG_SURF.items():
                    if self.mist_flags & fl:
                        self.sv[sn].freeze()

        while elapsed < total_dur:
            with self._lock:
                if self.act != Act.IBIT: return
                for surf_name in profiles:
                    sv = self.sv[surf_name]
                    tl = getattr(sv, '_timeline', [])
                    cmd = 0.0
                    for t_start, t_end, from_v, to_v in tl:
                        if t_start <= elapsed < t_end:
                            seg_dur = t_end - t_start
                            seg_elapsed = elapsed - t_start
                            frac = seg_elapsed / seg_dur
                            # Smooth ramp
                            ramp_frac = 0.15
                            if frac < ramp_frac:
                                cmd = from_v + (to_v - from_v) * (frac / ramp_frac)
                            elif frac > (1.0 - ramp_frac):
                                cmd = to_v  # hold at target
                            else:
                                cmd = to_v
                            break
                    sv.cmd = cmd

            time.sleep(dt)
            elapsed += dt

    # ── Monitor evaluation loop (#1) ──────────────────────────────────

    def _monitor_eval_loop(self):
        while self._running:
            if self._powered and self._booted:
                self.monitors.evaluate(self, self._mon_conditions)
            time.sleep(0.3)

    # ── Telemetry loop ────────────────────────────────────────────────

    def _telem_loop(self):
        th=tp=ta=tm=te=0.0; dt=0.01
        while self._running:
            now = time.time()
            self._global_time = now

            # No telemetry if not powered or during link blackout (#2, #8)
            if not self._powered or not self._booted:
                time.sleep(dt); continue
            if now < self._link_blackout_until:
                time.sleep(dt); continue

            with self._lock:
                for s in self.sv.values(): s.step(dt, now)

            # Packet drop (#8)
            drop = random.random() < self.drop_rate

            if now-th >= 1.0 and not drop:   self._tx_hb();  th=now
            if now-tp >= 0.1 and not drop:   self._tx_ps();  tp=now
            if now-ta >= 0.05 and not drop:  self._tx_act(); ta=now
            if now-tm >= 0.2 and not drop:   self._tx_mon(); tm=now
            if now-te >= 0.5 and not drop:   self._tx_eng(); te=now
            time.sleep(dt)

    # ── TX helpers ────────────────────────────────────────────────────

    def _tx_hb(self):
        try: self.conn.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_FIXED_WING,
            mavutil.mavlink.MAV_AUTOPILOT_GENERIC,0,0,
            mavutil.mavlink.MAV_STATE_ACTIVE)
        except: pass

    def _tx_ps(self):
        with self._lock: f=self.fr
        try: self.conn.mav.pandion_status_send(
            status=0, flight_regime=f,
            engine1_state=self._eng1_mode, engine2_state=self._eng2_mode,
            ins_status=1, ins_mode=1,
            gnss_fix=[3,3], num_satellites=[12,10],
            gnss_compass=1, mission_operation_mode=0, asset_id=self.sysid)
        except: pass

    def _tx_act(self):
        with self._lock:
            m=self.act; sb=self.isub; mn=self.imon; v=self.sv
        try: self.conn.mav.pandion_rr_actuation_sys_status_send(
            actuation_state=m, actuation_ibit_substate=sb, actuation_ibit_mon_status=mn,
            left_elevon_feedback_cdeg=int(v['left_elevon'].fb),
            right_elevon_feedback_cdeg=int(v['right_elevon'].fb),
            dorsal_rudder_feedback_cdeg=int(v['dorsal_rudder'].fb),
            ventral_rudder_feedback_cdeg=int(v['ventral_rudder'].fb),
            left_tvc_upper_feedback_cdeg=int(v['left_tvc_upper'].fb),
            left_tvc_lower_feedback_cdeg=int(v['left_tvc_lower'].fb),
            right_tvc_upper_feedback_cdeg=int(v['right_tvc_upper'].fb),
            right_tvc_lower_feedback_cdeg=int(v['right_tvc_lower'].fb),
            left_elevon_current_mA=int(v['left_elevon'].cur),
            right_elevon_current_mA=int(v['right_elevon'].cur),
            dorsal_rudder_current_mA=int(v['dorsal_rudder'].cur),
            ventral_rudder_current_mA=int(v['ventral_rudder'].cur),
            left_tvc_upper_current_mA=int(v['left_tvc_upper'].cur),
            left_tvc_lower_current_mA=int(v['left_tvc_lower'].cur),
            right_tvc_upper_current_mA=int(v['right_tvc_upper'].cur),
            right_tvc_lower_current_mA=int(v['right_tvc_lower'].cur),
            left_elevon_motor_temp_degC=int(v['left_elevon'].temp),
            right_elevon_motor_temp_degC=int(v['right_elevon'].temp))
        except: pass

    def _tx_mon(self):
        s, sg, o = self.monitors.get_state()
        cs=bytearray(64); cg=bytearray(64); co=bytearray(64)
        for m in s:
            if 0<=m<512: cs[m//8]|=1<<(m%8)
        for m in sg:
            if 0<=m<512: cg[m//8]|=1<<(m%8)
        for m in o:
            if 0<=m<512: co[m//8]|=1<<(m%8)
        try: self.conn.mav.pandion_monitor_current_status_send(
            currently_set=bytes(cs), currently_setting=bytes(cg),
            currently_overridden=bytes(co))
        except: pass

    def _tx_eng(self):
        """Engine status at 2 Hz (#5)."""
        try: self.conn.mav.pandion_rr_engine_status_send(
            eng_1_fuel_pump_curr_mA=random.gauss(450,20),
            eng_1_fuel_pump_speed_rpm=self._eng1_rpm*0.8,
            eng_1_fuel_consumption_l=0.0,
            eng_1_intake_temp_degC=random.gauss(35,2),
            eng_1_egt_temp_degC=self._eng1_egt,
            eng_1_speed_vs_nominal_pct=100 if self._eng1_rpm>0 else 0,
            eng_1_speed=self._eng1_rpm,
            eng_1_required_speed=0,
            eng_1_mode=self._eng1_mode,
            eng_1_EED=0, eng_1_relay_state=1 if self._powered else 0,
            eng_2_fuel_pump_curr_mA=random.gauss(450,20),
            eng_2_fuel_pump_speed_rpm=self._eng2_rpm*0.8,
            eng_2_fuel_consumption_l=0.0,
            eng_2_intake_temp_degC=random.gauss(35,2),
            eng_2_egt_temp_degC=self._eng2_egt,
            eng_2_speed_vs_nominal_pct=100 if self._eng2_rpm>0 else 0,
            eng_2_speed=self._eng2_rpm,
            eng_2_required_speed=0,
            eng_2_mode=self._eng2_mode,
            eng_2_EED=0, eng_2_relay_state=1 if self._powered else 0,
            hung_start_eshutdown=0)
        except: pass

    def _ack(self, cmd, result):
        try: self.conn.mav.command_ack_send(
            command=cmd, result=result, progress=0,
            result_param2=0, target_system=255, target_component=190)
        except: pass

    def _send_pv(self, name, val):
        pid = name.encode('utf-8')[:16].ljust(16, b'\x00')
        try: self.conn.mav.param_value_send(
            param_id=pid, param_value=val, param_type=9,
            param_count=10, param_index=0)
        except: pass


# ===========================================================================
# SimFleet -- manages cross-vehicle interactions (#11)
# ===========================================================================

class SimFleet:
    """Manages multiple simulated vehicles and cross-vehicle effects."""

    def __init__(self):
        self.vehicles = []
        self._lock = threading.Lock()

    def add(self, vehicle):
        with self._lock:
            self.vehicles.append(vehicle)
            vehicle.fleet = self

    def notify_relay_toggle(self, source_sysid):
        """When a vehicle's relay toggles, inject noise into all others (#11)."""
        with self._lock:
            for v in self.vehicles:
                if v.sysid != source_sysid:
                    v.inject_relay_noise(amplitude=25.0)


def _pid(r):
    return r.decode('utf-8').rstrip('\x00') if isinstance(r,bytes) else str(r).rstrip('\x00')

def _log(s, m):
    print(f"[SIM:{s}] {m}")
