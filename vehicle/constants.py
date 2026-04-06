"""
Vehicle Constants - Centralized definitions for modes, states, and enums

This module defines all the magic numbers used throughout the system to
ensure consistency and type safety.
"""
from enum import IntEnum


class ActuationMode(IntEnum):
    """
    Actuation system modes.
    
    These control the flight control actuators (elevons, rudders, TVC).
    """
    OFF = 0          # Actuators disabled, no power
    IBIT = 1         # Initiated Built-In Test (self-test mode)
    OPERATE = 2      # Normal flight-ready operation
    MANUAL = 3       # Manual control mode
    PLAYBACK = 4     # Playback recorded commands
    TRIM = 5         # Trim calibration mode
    POSITION_CHECK = 6  # Position verification
    TERMINAL = 7     # Terminal/shutdown mode


class IBITSubstate(IntEnum):
    """
    IBIT test sequence substates.
    
    The IBIT test progresses through these phases sequentially.
    Completion is detected by mode transition IBIT → OPERATE, not by
    reaching COMPLETE substate (vehicle may run multiple IBIT cycles).
    """
    BEGIN = 0              # Initialization
    WAIT_FOR_SETTLE = 1    # Waiting for stabilization
    ELEVONS = 2            # Testing wing control surfaces
    RUDDERS = 3            # Testing tail control surfaces
    TVC = 4                # Testing engine gimbal (Thrust Vector Control)
    COMPLETE = 5           # All tests passed


class FlightRegime(IntEnum):
    """
    Vehicle flight regime states.
    
    Defines the operational state of the vehicle from ground to flight.
    """
    GROUND_DISARMED = 0           # On ground, motors safe
    GROUND_ARMED = 1              # On ground, motors can spin (ARMED!)
    AUTO_TAKEOFF = 2              # Autonomous takeoff sequence
    HOVER = 3                     # Hovering in place
    FORWARD_TRANSITION = 4        # Transitioning to forward flight
    CRUISE = 5                    # Cruise flight mode
    IN_AIR_RESTART = 6            # Restarting systems in air
    BACK_TRANSITION = 7           # Transitioning back to hover
    EXTERNAL_GUIDANCE = 8         # External guidance control
    TAKEOFF_ABORTED = 9           # Takeoff abort procedure
    POWERING_OFF = 10             # Powering down sequence
    CUT_POWER = 11                # Emergency power cut
    TERMINATE = 12                # Termination mode
    SCUTTLE = 13                  # Scuttle sequence
    NULL_ATTITUDE_AND_COLLECTIVE = 14      # Null attitude control
    NULL_ATTITUDE_FIXED_COLLECTIVE = 15    # Fixed collective control
    LANDNOW_OL = 16               # Land now open-loop
    LANDNOW_CL = 17               # Land now closed-loop
    PILOT_OVERRIDE = 18           # Pilot override active
    EMERGENCY_STOP = 19           # Emergency stop engaged
    AUTO_RECOVERY = 20            # Automatic recovery mode
    WAVE_OFF = 21                 # Wave-off procedure
    TAXI = 22                     # Ground taxi mode
    INVALID = 255                 # Invalid/unknown regime


class CommandResult(IntEnum):
    """
    MAVLink command acknowledgment results.
    
    Standard MAV_RESULT enum values.
    """
    ACCEPTED = 0              # Command executed successfully
    TEMPORARILY_REJECTED = 1  # Command temporarily rejected, retry
    DENIED = 2                # Command permanently denied
    UNSUPPORTED = 3           # Command not supported
    FAILED = 4                # Command failed during execution
    IN_PROGRESS = 5           # Command still executing


class StatusTextSeverity(IntEnum):
    """
    Status text message severity levels.
    
    Standard syslog-style severity levels.
    """
    EMERGENCY = 0    # System unusable
    ALERT = 1        # Action must be taken immediately
    CRITICAL = 2     # Critical conditions
    ERROR = 3        # Error conditions
    WARNING = 4      # Warning conditions
    NOTICE = 5       # Normal but significant
    INFO = 6         # Informational messages
    DEBUG = 7        # Debug-level messages


# Display name mappings for enums
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
    IBITSubstate.BEGIN: "BEGIN (Initializing)",
    IBITSubstate.WAIT_FOR_SETTLE: "WAIT_FOR_SETTLE (Stabilizing)",
    IBITSubstate.ELEVONS: "ELEVONS (Wing controls)",
    IBITSubstate.RUDDERS: "RUDDERS (Tail controls)",
    IBITSubstate.TVC: "TVC (Engine gimbals)",
    IBITSubstate.COMPLETE: "COMPLETE (All tests passed)",
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

# Default values for sensor readings
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

# Heartbeat configuration
HEARTBEAT_INTERVAL = 1.0               # seconds (1 Hz)
HEARTBEAT_INITIAL_BURST = 3            # Number of initial heartbeats

# Monitor override commands
MONITOR_OVERRIDE_CLEAR = 0             # Clear override
MONITOR_OVERRIDE_SET = 1               # Set override
MONITOR_OVERRIDE_CLEAR_SPECIFIC = 2    # Clear specific monitor


def get_actuation_mode_name(mode: int) -> str:
    """
    Get human-readable name for actuation mode.
    
    Args:
        mode: Actuation mode number
    
    Returns:
        Mode name string
    """
    try:
        return ACTUATION_MODE_NAMES.get(ActuationMode(mode), f"UNKNOWN({mode})")
    except ValueError:
        return f"UNKNOWN({mode})"


def get_ibit_substate_name(substate: int) -> str:
    """
    Get human-readable name for IBIT substate.
    
    Args:
        substate: IBIT substate number
    
    Returns:
        Substate name string
    """
    try:
        return IBIT_SUBSTATE_NAMES.get(IBITSubstate(substate), f"UNKNOWN({substate})")
    except ValueError:
        return f"UNKNOWN({substate})"


def get_flight_regime_name(regime: int) -> str:
    """
    Get human-readable name for flight regime.
    
    Args:
        regime: Flight regime number
    
    Returns:
        Regime name string
    """
    try:
        return FLIGHT_REGIME_NAMES.get(FlightRegime(regime), f"REGIME_{regime}")
    except ValueError:
        return f"REGIME_{regime}"


def is_armed(flight_regime: int) -> bool:
    """
    Determine if vehicle is armed based on flight regime.
    
    Args:
        flight_regime: Flight regime number
    
    Returns:
        True if vehicle is armed (motors can spin)
    """
    return flight_regime >= FlightRegime.GROUND_ARMED and flight_regime != FlightRegime.INVALID
