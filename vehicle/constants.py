from __future__ import annotations

"""
Vehicle Constants - Centralized definitions for modes, states, and enums.

This module is the **single source of truth** for all magic numbers, display
names, and lookup tables used throughout the production test system.  Every
other module imports from here rather than defining its own inline dicts.
"""
from typing import List

from enum import IntEnum


# ═══════════════════════════════════════════════════════════════════════════════
# Vehicle enums (from Pandion firmware)
# ═══════════════════════════════════════════════════════════════════════════════

class ActuationMode(IntEnum):
    """Actuation system modes — control the flight actuators."""
    OFF = 0            # Actuators disabled, no power
    IBIT = 1           # Initiated Built-In Test (self-test mode)
    OPERATE = 2        # Normal flight-ready operation
    MANUAL = 3         # Manual control mode
    PLAYBACK = 4       # Playback recorded commands
    TRIM = 5           # Trim calibration mode
    POSITION_CHECK = 6 # Position verification
    TERMINAL = 7       # Terminal/shutdown mode


class IBITSubstate(IntEnum):
    """IBIT test sequence substates (progresses sequentially)."""
    BEGIN = 0              # Initialization
    WAIT_FOR_SETTLE = 1    # Waiting for stabilization
    ELEVONS = 2            # Testing wing control surfaces
    RUDDERS = 3            # Testing tail control surfaces
    TVC = 4                # Testing engine gimbal (Thrust Vector Control)
    COMPLETE = 5           # All tests passed


class FlightRegime(IntEnum):
    """Vehicle flight regime states — ground to flight."""
    GROUND_DISARMED = 0
    GROUND_ARMED = 1
    AUTO_TAKEOFF = 2
    HOVER = 3
    FORWARD_TRANSITION = 4
    CRUISE = 5
    IN_AIR_RESTART = 6
    BACK_TRANSITION = 7
    EXTERNAL_GUIDANCE = 8
    TAKEOFF_ABORTED = 9
    POWERING_OFF = 10
    CUT_POWER = 11
    TERMINATE = 12
    SCUTTLE = 13
    NULL_ATTITUDE_AND_COLLECTIVE = 14
    NULL_ATTITUDE_FIXED_COLLECTIVE = 15
    LANDNOW_OL = 16
    LANDNOW_CL = 17
    PILOT_OVERRIDE = 18
    EMERGENCY_STOP = 19
    AUTO_RECOVERY = 20
    WAVE_OFF = 21
    TAXI = 22
    INVALID = 255


class CommandResult(IntEnum):
    """MAVLink command acknowledgment results (MAV_RESULT)."""
    ACCEPTED = 0
    TEMPORARILY_REJECTED = 1
    DENIED = 2
    UNSUPPORTED = 3
    FAILED = 4
    IN_PROGRESS = 5


class StatusTextSeverity(IntEnum):
    """Status text message severity levels (syslog)."""
    EMERGENCY = 0
    ALERT = 1
    CRITICAL = 2
    ERROR = 3
    WARNING = 4
    NOTICE = 5
    INFO = 6
    DEBUG = 7


# ═══════════════════════════════════════════════════════════════════════════════
# Application-level enums (not from firmware)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMode:
    """Test mode identifiers — used as string constants throughout the UI."""
    IBIT = 'ibit'
    PLAYBACK = 'playback'


class UUTStatus:
    """UUT status values — used as string constants in the UUT table."""
    READY = "Ready"
    TESTING = "Testing"
    COMPLETE = "Complete"
    FAILED = "Failed"
    FAILED_PERMANENT = "Failed (3x)"
    RETRY = "Retry"
    STOPPED = "Stopped"


class AlertSeverity:
    """Alert banner severity levels."""
    WARNING = 'warning'
    ERROR = 'error'
    CRITICAL = 'critical'
    INFO = 'info'


# ═══════════════════════════════════════════════════════════════════════════════
# Display name mappings
# ═══════════════════════════════════════════════════════════════════════════════

# Short mode names for log messages and status display
MODE_NAMES = {
    ActuationMode.OFF: "OFF",
    ActuationMode.IBIT: "IBIT",
    ActuationMode.OPERATE: "OPERATE",
    ActuationMode.MANUAL: "MANUAL",
    ActuationMode.PLAYBACK: "PLAYBACK",
    ActuationMode.TRIM: "TRIM",
    ActuationMode.POSITION_CHECK: "POSITION_CHECK",
    ActuationMode.TERMINAL: "TERMINAL",
}

# Verbose mode names (with descriptions) for detailed display
ACTUATION_MODE_NAMES = {
    ActuationMode.OFF: "OFF (Disabled)",
    ActuationMode.IBIT: "IBIT (Self-test)",
    ActuationMode.OPERATE: "OPERATE (Flight-ready)",
    ActuationMode.MANUAL: "MANUAL (Manual control)",
    ActuationMode.PLAYBACK: "PLAYBACK (Recording playback)",
    ActuationMode.TRIM: "TRIM (Calibration)",
    ActuationMode.POSITION_CHECK: "POSITION_CHECK (Verification)",
    ActuationMode.TERMINAL: "TERMINAL (Shutdown)",
}

IBIT_SUBSTATE_NAMES = {
    IBITSubstate.BEGIN: "BEGIN",
    IBITSubstate.WAIT_FOR_SETTLE: "WAIT_FOR_SETTLE",
    IBITSubstate.ELEVONS: "ELEVONS",
    IBITSubstate.RUDDERS: "RUDDERS",
    IBITSubstate.TVC: "TVC",
    IBITSubstate.COMPLETE: "COMPLETE",
}

# GUI display names for IBIT substates (with checkmark on COMPLETE)
IBIT_SUBSTATE_DISPLAY_NAMES = {
    IBITSubstate.BEGIN: "BEGIN",
    IBITSubstate.WAIT_FOR_SETTLE: "WAIT_FOR_SETTLE",
    IBITSubstate.ELEVONS: "ELEVONS",
    IBITSubstate.RUDDERS: "RUDDERS",
    IBITSubstate.TVC: "TVC",
    IBITSubstate.COMPLETE: "\u2713 COMPLETE",
}

FLIGHT_REGIME_NAMES = {
    FlightRegime.GROUND_DISARMED: "GROUND_DISARMED",
    FlightRegime.GROUND_ARMED: "GROUND_ARMED",
    FlightRegime.AUTO_TAKEOFF: "AUTO_TAKEOFF",
    FlightRegime.HOVER: "HOVER",
    FlightRegime.FORWARD_TRANSITION: "FORWARD_TRANSITION",
    FlightRegime.CRUISE: "CRUISE",
    FlightRegime.IN_AIR_RESTART: "IN_AIR_RESTART",
    FlightRegime.BACK_TRANSITION: "BACK_TRANSITION",
    FlightRegime.EXTERNAL_GUIDANCE: "EXTERNAL_GUIDANCE",
    FlightRegime.TAKEOFF_ABORTED: "TAKEOFF_ABORTED",
    FlightRegime.POWERING_OFF: "POWERING_OFF",
    FlightRegime.CUT_POWER: "CUT_POWER",
    FlightRegime.TERMINATE: "TERMINATE",
    FlightRegime.SCUTTLE: "SCUTTLE",
    FlightRegime.NULL_ATTITUDE_AND_COLLECTIVE: "NULL_ATTITUDE_AND_COLLECTIVE",
    FlightRegime.NULL_ATTITUDE_FIXED_COLLECTIVE: "NULL_ATTITUDE_FIXED_COLLECTIVE",
    FlightRegime.LANDNOW_OL: "LANDNOW_OL",
    FlightRegime.LANDNOW_CL: "LANDNOW_CL",
    FlightRegime.PILOT_OVERRIDE: "PILOT_OVERRIDE",
    FlightRegime.EMERGENCY_STOP: "EMERGENCY_STOP",
    FlightRegime.AUTO_RECOVERY: "AUTO_RECOVERY",
    FlightRegime.WAVE_OFF: "WAVE_OFF",
    FlightRegime.TAXI: "TAXI",
    FlightRegime.INVALID: "INVALID",
}

# Short regime names for compact UI display (StatusPanelWidget)
FLIGHT_REGIME_SHORT_NAMES = {
    FlightRegime.GROUND_DISARMED: "DISARMED",
    FlightRegime.GROUND_ARMED: "ARMED",
    FlightRegime.AUTO_TAKEOFF: "AUTO_TAKEOFF",
    FlightRegime.HOVER: "HOVER",
    FlightRegime.FORWARD_TRANSITION: "FWD_TRANS",
    FlightRegime.CRUISE: "CRUISE",
    FlightRegime.INVALID: "INVALID",
}

COMMAND_RESULT_NAMES = {
    CommandResult.ACCEPTED: "ACCEPTED",
    CommandResult.TEMPORARILY_REJECTED: "TEMPORARILY_REJECTED",
    CommandResult.DENIED: "DENIED",
    CommandResult.UNSUPPORTED: "UNSUPPORTED",
    CommandResult.FAILED: "FAILED",
    CommandResult.IN_PROGRESS: "IN_PROGRESS",
}

SEVERITY_NAMES = {
    StatusTextSeverity.EMERGENCY: "EMERGENCY",
    StatusTextSeverity.ALERT: "ALERT",
    StatusTextSeverity.CRITICAL: "CRITICAL",
    StatusTextSeverity.ERROR: "ERROR",
    StatusTextSeverity.WARNING: "WARNING",
    StatusTextSeverity.NOTICE: "NOTICE",
    StatusTextSeverity.INFO: "INFO",
    StatusTextSeverity.DEBUG: "DEBUG",
}

# ═══════════════════════════════════════════════════════════════════════════════
# Mistracking flags — PANDION_RR_IBIT_MON_STATUS bitmask
# ═══════════════════════════════════════════════════════════════════════════════

MISTRACKING_FLAG_NAMES = {
    1:   'Upper Rudder',
    2:   'Lower Rudder',
    4:   'Left TVC Upper',
    8:   'Left TVC Lower',
    16:  'Right TVC Upper',
    32:  'Right TVC Lower',
    64:  'Left Elevon',
    128: 'Right Elevon',
}

# ═══════════════════════════════════════════════════════════════════════════════
# MAVLink message type strings (single source of truth)
# ═══════════════════════════════════════════════════════════════════════════════

class MsgType:
    """MAVLink message type strings used throughout the codebase."""
    HEARTBEAT = 'HEARTBEAT'
    PANDION_STATUS = 'PANDION_STATUS'
    ACTUATION_SYS_STATUS = 'PANDION_RR_ACTUATION_SYS_STATUS'
    MONITOR_STATUS = 'PANDION_MONITOR_CURRENT_STATUS'
    COMMAND_ACK = 'COMMAND_ACK'
    PARAM_VALUE = 'PARAM_VALUE'
    STATUSTEXT = 'STATUSTEXT'
    ENGINE_STATUS = 'PANDION_RR_ENGINE_STATUS'
    BMS_DATA = 'PANDION_RR_BMS_DATA'
    WCA_STATUS = 'PANDION_WCA_MONITOR_STATUS'
    PDU_POWER = 'PANDION_RR_PDU_TELEMETRY_POWER'
    HW_SELECTOR = 'PANDION_RR_HARDWARE_SELECTOR_STATUS'
    PLAYBACK_COMMAND = 'PANDION_RR_PLAYBACK_COMMAND'


# ═══════════════════════════════════════════════════════════════════════════════
# Default values
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_ACTUATOR_POSITION_CDEG = -5500  # Centidegrees (invalid sensor reading)
DEFAULT_ACTUATOR_POSITION_DEG = -55.0   # Degrees

# Timeout values (can be overridden by config)
DEFAULT_CONNECTION_TIMEOUT = 10.0      # seconds
DEFAULT_HEARTBEAT_TIMEOUT = 3.0        # seconds
DEFAULT_COMMAND_ACK_TIMEOUT = 2.0      # seconds
DEFAULT_STATE_QUERY_TIMEOUT = 5.0      # seconds
DEFAULT_IBIT_TIMEOUT = 300.0           # seconds
DEFAULT_PHASE_TIMEOUT = 90.0           # seconds
DEFAULT_ARM_TIMEOUT = 60.0             # seconds
DEFAULT_STABILIZATION_DELAY = 2.0      # seconds
DEFAULT_MAX_ARM_ITERATIONS = 20
DEFAULT_MAX_CONSECUTIVE_FAILURES = 3

# Relay safety
RELAY_DISABLE_MAX_ATTEMPTS = 5
RELAY_DISABLE_RETRY_DELAY = 0.5        # seconds

# Telemetry worker
MAX_CONSECUTIVE_TELEMETRY_ERRORS = 10

# IBIT monitor
OPERATE_WAIT_TIMEOUT = 10.0            # seconds after IBIT completion

# Heartbeat configuration
HEARTBEAT_INTERVAL = 1.0               # seconds (1 Hz)
HEARTBEAT_INITIAL_BURST = 3            # Number of initial heartbeats
HEARTBEAT_BURST_INTERVAL = 0.1         # seconds between burst heartbeats

# Log monitoring
LOG_SIZE_CHECK_INTERVAL = 30.0         # seconds
STATS_UPDATE_INTERVAL = 2.0            # seconds

# DAQ health
DAQ_HEALTH_CHECK_INTERVAL = 60000      # milliseconds (1 minute)

# Monitor override commands
MONITOR_OVERRIDE_CLEAR = 0             # Clear override
MONITOR_OVERRIDE_SET = 1               # Set override
MONITOR_OVERRIDE_CLEAR_SPECIFIC = 2    # Clear specific monitor

# USE_NEST parameter values
USE_NEST_ENABLED = 1
USE_NEST_DISABLED = 0


# ═══════════════════════════════════════════════════════════════════════════════
# Lookup helpers
# ═══════════════════════════════════════════════════════════════════════════════

def get_mode_name(mode: int) -> str:
    """Get short mode name (e.g. 'OPERATE') for an actuation mode number."""
    return MODE_NAMES.get(mode, f"UNKNOWN({mode})")


def get_actuation_mode_name(mode: int) -> str:
    """Get verbose mode name (e.g. 'OPERATE (Flight-ready)') for display."""
    try:
        return ACTUATION_MODE_NAMES.get(ActuationMode(mode), f"UNKNOWN({mode})")
    except ValueError:
        return f"UNKNOWN({mode})"


def get_ibit_substate_name(substate: int) -> str:
    """Get IBIT substate name."""
    return IBIT_SUBSTATE_NAMES.get(substate, f"UNKNOWN({substate})")


def get_flight_regime_name(regime: int) -> str:
    """Get flight regime name."""
    return FLIGHT_REGIME_NAMES.get(regime, f"REGIME_{regime}")


def get_flight_regime_short_name(regime: int) -> str:
    """Get short regime name for compact display."""
    return FLIGHT_REGIME_SHORT_NAMES.get(regime, f"REGIME {regime}")


def get_command_result_name(result: int) -> str:
    """Get command result name."""
    return COMMAND_RESULT_NAMES.get(result, f"UNKNOWN({result})")


def get_severity_name(severity: int) -> str:
    """Get severity level name."""
    return SEVERITY_NAMES.get(severity, f"SEV{severity}")


def get_failed_surfaces(mistracking_flags: int) -> List[str]:
    """Get list of surface names from a mistracking bitmask."""
    return [
        name for bit, name in MISTRACKING_FLAG_NAMES.items()
        if mistracking_flags & bit
    ]


def is_armed(flight_regime: int) -> bool:
    """True if vehicle is armed (motors can spin)."""
    return flight_regime >= FlightRegime.GROUND_ARMED and flight_regime != FlightRegime.INVALID
