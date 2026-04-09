# -*- coding: utf-8 -*-
"""
sim.config.defaults -- Constants, enums, and default configuration.

Single source of truth for all magic numbers, state enums, IBIT profiles,
monitor definitions, and tuning parameters used across the simulator.
"""

# Import production enums as the canonical source of truth
from vehicle.constants import (
    ActuationMode as _ActuationMode,
    IBITSubstate as _IBITSubstate,
    FlightRegime as _FlightRegime,
    MONITOR_OVERRIDE_CANCEL,
    MONITOR_OVERRIDE_SUPPRESS,
    MONITOR_OVERRIDE_FORCE_FAULT,
)


# ═══════════════════════════════════════════════════════════════════════════════
# State enums — sim aliases mapping to production enums
# ═══════════════════════════════════════════════════════════════════════════════

class FlightRegime:
    """Flight regime aliases for sim compatibility."""
    DISARMED       = _FlightRegime.GROUND_DISARMED        # 0
    ARMED          = _FlightRegime.GROUND_ARMED            # 1
    AUTO_TAKEOFF   = _FlightRegime.AUTO_TAKEOFF            # 2
    HOVER          = _FlightRegime.HOVER                   # 3
    CRUISE         = _FlightRegime.CRUISE                  # 5
    POWERING_OFF   = _FlightRegime.POWERING_OFF            # 10
    CUT_POWER      = _FlightRegime.CUT_POWER               # 11
    TERMINATE      = _FlightRegime.TERMINATE                # 12
    EMERGENCY_STOP = _FlightRegime.EMERGENCY_STOP          # 19
    INVALID        = _FlightRegime.INVALID                  # 255


class ActuationState:
    """Actuation state aliases for sim compatibility."""
    OFF       = _ActuationMode.OFF
    OPERATE   = _ActuationMode.OPERATE
    PLAYBACK  = _ActuationMode.PLAYBACK
    IBIT      = _ActuationMode.IBIT
    MANUAL    = _ActuationMode.MANUAL
    TRIM      = _ActuationMode.TRIM
    POS_CHECK = _ActuationMode.POSITION_CHECK
    TERMINAL  = _ActuationMode.TERMINAL

    NAMES = {
        _ActuationMode.OFF: "OFF",
        _ActuationMode.IBIT: "IBIT",
        _ActuationMode.OPERATE: "OPERATE",
        _ActuationMode.MANUAL: "MANUAL",
        _ActuationMode.PLAYBACK: "PLAYBACK",
        _ActuationMode.TRIM: "TRIM",
        _ActuationMode.POSITION_CHECK: "POS_CHECK",
        _ActuationMode.TERMINAL: "TERMINAL",
    }

    # Valid transitions: (from, to)
    VALID_TRANSITIONS = {
        (OPERATE, PLAYBACK),
        (PLAYBACK, IBIT),
        (IBIT, OPERATE),
        (PLAYBACK, OPERATE),
        (MANUAL, OPERATE),
    }


class IBITSubstate:
    """IBIT substate aliases for sim compatibility."""
    BEGIN   = _IBITSubstate.BEGIN
    SETTLE  = _IBITSubstate.WAIT_FOR_SETTLE
    ELEVON  = _IBITSubstate.ELEVONS
    RUDDERS = _IBITSubstate.RUDDERS
    TVC     = _IBITSubstate.TVC
    DONE    = _IBITSubstate.COMPLETE

    NAMES = {
        _IBITSubstate.BEGIN: "BEGIN",
        _IBITSubstate.WAIT_FOR_SETTLE: "SETTLE",
        _IBITSubstate.ELEVONS: "ELEVON",
        _IBITSubstate.RUDDERS: "RUDDERS",
        _IBITSubstate.TVC: "TVC",
        _IBITSubstate.COMPLETE: "DONE",
    }
    SEQUENCE = [BEGIN, SETTLE, ELEVON, RUDDERS, TVC, DONE]


class MistrackingFlags:
    UPPER_RUDDER    = 1
    LOWER_RUDDER    = 2
    LEFT_TVC_UPPER  = 4
    LEFT_TVC_LOWER  = 8
    RIGHT_TVC_UPPER = 16
    RIGHT_TVC_LOWER = 32
    LEFT_ELEVON     = 64
    RIGHT_ELEVON    = 128

    FLAG_TO_SURFACE = {
        LEFT_ELEVON:     'left_elevon',
        RIGHT_ELEVON:    'right_elevon',
        UPPER_RUDDER:    'dorsal_rudder',
        LOWER_RUDDER:    'ventral_rudder',
        LEFT_TVC_UPPER:  'left_tvc_upper',
        LEFT_TVC_LOWER:  'left_tvc_lower',
        RIGHT_TVC_UPPER: 'right_tvc_upper',
        RIGHT_TVC_LOWER: 'right_tvc_lower',
    }


class INSStatus:
    OFF      = 0
    ALIGNING = 1
    DEGRADED = 2
    FULL     = 3


class GNSSFix:
    NO_FIX    = 0
    FIX_2D    = 2
    FIX_3D    = 3
    RTK_FLOAT = 4
    RTK_FIXED = 5


# ═══════════════════════════════════════════════════════════════════════════════
# Surface names
# ═══════════════════════════════════════════════════════════════════════════════

SURFACE_NAMES = [
    'left_elevon', 'right_elevon',
    'dorsal_rudder', 'ventral_rudder',
    'left_tvc_upper', 'left_tvc_lower',
    'right_tvc_upper', 'right_tvc_lower',
]


# ═══════════════════════════════════════════════════════════════════════════════
# IBIT configuration (from actuation.c in roadrunner/pandion_roadrunner)
# ═══════════════════════════════════════════════════════════════════════════════

# IBIT phase durations (seconds) — from firmware #defines
IBIT_PHASE_DURATIONS = {
    0: 0.5,     # BEGIN (instant transition, small buffer)
    1: 0.5,     # WAIT_FOR_SETTLE = 500ms
    2: 5.0,     # ELEVON = 5000ms
    3: 10.0,    # RUDDERS = 10000ms
    4: 5.0,     # TVC = 5000ms
    # No COMPLETE phase — firmware transitions immediately to OPERATE
}

# IBIT command profiles:
#
# Elevon/Rudder: ibit_linear_function(percent) from actuation.c:
#   0-25%:   lerp 0 -> -1
#   25-75%:  lerp -1 -> +1
#   75-100%: lerp +1 -> 0
# This is a symmetric triangle wave normalized to [-1, +1].
# The multiplier is applied to IBIT_AERO_PitchAccelCmd (elevon) or
# IBIT_AERO_RollAccelCmd (rudder) which feeds into ControlAllocation.
#
# TVC: circular/square pattern using cos(angle) * radial_scale:
#   0-25%:   radial lerp 0->1, angle sweeps
#   25-75%:  square pattern (radial = 1/cos or 1/sin)
#   75-100%: radial lerp 1->0
#
# Nest-connected coefficients (from actuation.c):
#   ibit_coeffs_nest = { .elev = 0.75, .rudd = 0.05, .tvc = 0.60 }
#
# We don't replicate the full ControlAllocation Simulink model, so we
# approximate the output surface commands based on the multiplier range.

IBIT_NEST_COEFFS = {
    'elev': 0.75,
    'rudd': 0.05,
    'tvc':  0.60,
}

# IBIT deflection attenuation when nest is connected
NEST_IBIT_ATTEN_ELEVON = 0.75
NEST_IBIT_ATTEN_RUDDER = 0.05
NEST_IBIT_ATTEN_TVC = 0.60

# Servo hard limits (cdeg) — from firmware clamp_to_servo_limits()
SERVO_HARD_LIMIT_ELEVON_CDEG = 3500   # ±35°
SERVO_HARD_LIMIT_RUDDER_CDEG = 6000   # ±60°
SERVO_HARD_LIMIT_TVC_CDEG = 6000      # ±60°

# Servo hard limits dict (convenience accessor used by vehicle.py)
SERVO_HARD_LIMITS = {
    'elevon': SERVO_HARD_LIMIT_ELEVON_CDEG,
    'rudder': SERVO_HARD_LIMIT_RUDDER_CDEG,
    'tvc':    SERVO_HARD_LIMIT_TVC_CDEG,
}

# IBIT profiles are now computed dynamically by the vehicle sim using
# ibit_linear_function() for elevon/rudder and circular pattern for TVC.
# The old static profiles are removed.
IBIT_PROFILES = None  # Computed at runtime by vehicle.py


# ═══════════════════════════════════════════════════════════════════════════════
# Monitor definitions
# ═══════════════════════════════════════════════════════════════════════════════

# Safety-critical monitors that abort IBIT if asserted
SAFETY_CRITICAL_MONITOR_IDS = {50, 51, 52}

# ARM force magic number (param2 of MAV_CMD_COMPONENT_ARM_DISARM)
ARM_FORCE_MAGIC = 21196

# Parameters that require a power cycle to take effect
REBOOT_REQUIRED_PARAMS = {'CLASSIC_MODE_EN', 'STBL_PRMS_APPVD'}

# Default parameter values
DEFAULT_PARAMS = {
    'USE_NEST': 0,
    'CLASSIC_MODE_EN': 0,
    'STBL_PRMS_APPVD': 0,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Servo tuning (from actuation.c)
# ═══════════════════════════════════════════════════════════════════════════════

SERVO_TAU             = 0.02      # First-order lag time constant (seconds) - fast enough to track within 500cdeg
SERVO_MAX_SLEW_CDEG_S = 1500.0   # was 9000 — from firmware MANUAL_MAX_RATE_CDEG_SEC
SERVO_DEADBAND_CDEG   = 5.0      # No response below this error

# Mistracking detection (from actuation.c lines 33-35):
#   IBIT_TVC_SERVO_TRACKING_MAX_DELTA_CDEG = 500 (5 degrees)
#   IBIT_TVC_CONSEC_MISTRACK_THRESHOLD_MS  = 50
#   At 100Hz task rate: 5 consecutive cycles
#
# Elevon/rudder mistracking is INSTANT (no cycle counter).
# TVC mistracking requires consecutive cycles above threshold.
SERVO_MISTRACK_THRESH_CDEG         = 500.0   # 5 degrees (NOT 50 cdeg)
SERVO_TVC_CONSEC_MISTRACK_CYCLES   = 5       # 50ms at 100Hz
SERVO_ELEVON_MISTRACK_INSTANT      = True    # Elevon/rudder: instant detect

SERVO_THERMAL_SHUTDOWN = 83.0    # Servo shuts down above this temp (degC)
SERVO_THERMAL_RESTART  = 75.0    # Servo restarts below this temp (degC)

# Manual mode rate limit from actuation.c
MANUAL_MAX_RATE_CDEG_SEC = 1500.0


# ═══════════════════════════════════════════════════════════════════════════════
# Telemetry rates
# ═══════════════════════════════════════════════════════════════════════════════

# Telemetry rates (Hz) — from vehicle_cycle_task_table.h
RATE_HEARTBEAT      = 1.0     # 1 Hz (was 10 Hz)
RATE_PANDION_STATUS = 10.0    # 10 Hz
RATE_ACTUATION      = 5.0     # 5 Hz (was 20 Hz) — firmware sends at 5 Hz
RATE_MONITOR        = 5.0     # 5 Hz
RATE_MONITORS       = RATE_MONITOR  # alias used by vehicle.py
RATE_ENGINE         = 2.0     # 2 Hz
RATE_BMS            = 1.0     # 1 Hz
RATE_WCA            = 1.0     # 1 Hz
RATE_PDU            = 0.5     # 0.5 Hz
RATE_HW_SELECTOR    = 0.2     # 0.2 Hz


# ═══════════════════════════════════════════════════════════════════════════════
# Battery defaults
# ═══════════════════════════════════════════════════════════════════════════════

BMS_CAPACITY_MAH        = 5000
BMS_CELLS               = 7
BMS_VOLTAGE_PER_CELL_MV = 3700
BMS_UNDERVOLTAGE_MV     = 21000  # Monitor triggers below this


# ═══════════════════════════════════════════════════════════════════════════════
# MAVLink type
# ═══════════════════════════════════════════════════════════════════════════════

MAV_TYPE_VTOL_DUOROTOR = 29  # firmware uses this, not FIXED_WING


# ═══════════════════════════════════════════════════════════════════════════════
# Actuation task rate — firmware runs at 100Hz
# ═══════════════════════════════════════════════════════════════════════════════

ACTUATION_TASK_RATE_HZ = 100
ACTUATION_TASK_DT = 1.0 / ACTUATION_TASK_RATE_HZ  # 0.01s


# ═══════════════════════════════════════════════════════════════════════════════
# Mistracking detection — from firmware perform_monitoring()
# ═══════════════════════════════════════════════════════════════════════════════

IBIT_MISTRACK_THRESHOLD_CDEG = 500        # 5° for all surfaces
IBIT_TVC_CONSEC_MISTRACK_MS = 50          # 50ms consecutive for TVC
IBIT_TVC_CONSEC_MISTRACK_CYCLES = 5       # 50ms at 100Hz = 5 cycles
