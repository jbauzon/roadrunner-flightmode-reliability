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
    MONITOR_OVERRIDE_CLEAR,
    MONITOR_OVERRIDE_SET,
    MONITOR_OVERRIDE_CLEAR_SPECIFIC,
)


# ═══════════════════════════════════════════════════════════════════════════════
# State enums — sim aliases mapping to production enums
# ═══════════════════════════════════════════════════════════════════════════════

class FlightRegime:
    """Flight regime aliases for sim compatibility."""
    DISARMED = _FlightRegime.GROUND_DISARMED
    ARMED    = _FlightRegime.GROUND_ARMED


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

# Duration per IBIT phase at scale=1.0 (seconds)
# Source: actuation.c lines 30-32
IBIT_PHASE_DURATIONS = {
    IBITSubstate.BEGIN:   0.0,    # Immediate transition to SETTLE
    IBITSubstate.SETTLE:  0.5,    # IBIT_ZERO_SETTLE_TIME_MS = 500
    IBITSubstate.ELEVON:  5.0,    # IBIT_ELEVON_TEST_TIME_MS = 5000
    IBITSubstate.RUDDERS: 10.0,   # IBIT_RUDDERS_TEST_TIME_MS = 10000
    IBITSubstate.TVC:     5.0,    # IBIT_TVC_TEST_TIME_MS = 5000
    IBITSubstate.DONE:    0.0,    # Immediate transition to OPERATE
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

# Servo hard limits (cdeg) from actuation.c
SERVO_HARD_LIMITS = {
    'elevon': 3500,
    'rudder': 6000,
    'tvc':    6000,
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
SERVO_MAX_SLEW_CDEG_S = 40000.0  # ~400 deg/s
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

RATE_HEARTBEAT      = 1.0     # Hz
RATE_PANDION_STATUS = 10.0    # Hz
RATE_ACTUATION      = 20.0    # Hz
RATE_MONITORS       = 5.0     # Hz
RATE_ENGINE         = 2.0     # Hz
RATE_BMS            = 1.0     # Hz
RATE_WCA            = 0.5     # Hz
RATE_PDU            = 0.2     # Hz
RATE_HW_SELECTOR    = 0.2     # Hz


# ═══════════════════════════════════════════════════════════════════════════════
# Battery defaults
# ═══════════════════════════════════════════════════════════════════════════════

BMS_CAPACITY_MAH        = 5000
BMS_CELLS               = 7
BMS_VOLTAGE_PER_CELL_MV = 3700
BMS_UNDERVOLTAGE_MV     = 21000  # Monitor triggers below this
