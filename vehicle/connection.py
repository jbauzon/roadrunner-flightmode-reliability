from __future__ import annotations

"""
Vehicle Connection - MAVLink communication and state management
This module handles low-level MAVLink communication with flight controllers.
Includes UUT definition and state capture classes.
"""
import sys
import os
import ipaddress
from typing import Any, Dict, List, Optional

from pymavlink import mavutil
from .constants import UUTStatus, USE_NEST_ENABLED, DEFAULT_VEHICLE_PORT, get_mode_name, get_flight_regime_name

class UUT:
    """
    Unit Under Test definition with input validation.
    
    Represents a single flight controller being tested.
    """
    
    MAX_RELAY_LINES = 32  # System maximum relay lines
    
    def __init__(self, serial_number: str = "", ip_address: str = "", port: int = DEFAULT_VEHICLE_PORT, relay_line: int = 0) -> None:
        """
        Initialize UUT with validation.
        
        Args:
            serial_number: Unique identifier for this UUT
            ip_address: Network address of vehicle (must be valid IP)
            port: MAVLink UDP port (1-65535, default: 13002)
            relay_line: Which DAQ line controls power (0-31)
        
        Raises:
            ValueError: If any parameter is invalid
            TypeError: If parameter types are incorrect
        """
        # Validate serial_number
        if not isinstance(serial_number, str):
            raise TypeError(f"serial_number must be str, got {type(serial_number)}")
        
        # Validate and normalize IP address
        if ip_address:  # Allow empty for creation, validate on use
            try:
                # This will raise ValueError if invalid
                ip = ipaddress.ip_address(ip_address)
                ip_address = str(ip)  # Normalize
            except ValueError as e:
                raise ValueError(f"Invalid IP address '{ip_address}': {e}")
        
        # Validate port
        if not isinstance(port, int):
            raise TypeError(f"port must be int, got {type(port)}")
        if not (1 <= port <= 65535):
            raise ValueError(f"port must be 1-65535, got {port}")
        
        # Validate relay_line
        if not isinstance(relay_line, int):
            raise TypeError(f"relay_line must be int, got {type(relay_line)}")
        if not (0 <= relay_line < self.MAX_RELAY_LINES):
            raise ValueError(
                f"relay_line must be 0-{self.MAX_RELAY_LINES-1}, got {relay_line}"
            )
        
        self.serial_number = serial_number
        self.ip_address = ip_address
        self.port = port
        self.relay_line = relay_line
        self.status = UUTStatus.READY
        self.test_start_time = None
        self.test_end_time = None
        self.iterations_completed = 0
        self.log_file = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for saving"""
        return {
            'serial_number': self.serial_number,
            'ip_address': self.ip_address,
            'port': self.port,
            'relay_line': self.relay_line
        }
    
    def __repr__(self) -> str:
        return f"UUT({self.serial_number!r}, {self.ip_address}:{self.port}, relay={self.relay_line})"
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> UUT:
        """Create from dictionary"""
        return UUT(
            serial_number=data.get('serial_number', ''),
            ip_address=data.get('ip_address', ''),
            port=data.get('port', DEFAULT_VEHICLE_PORT),
            relay_line=data.get('relay_line', 0)
        )

class UUTState:
    """
    Captures the complete state of a UUT.
    
    Used for state capture and restoration to ensure vehicle
    returns to original configuration after testing.
    """
    
    def __init__(self) -> None:
        """Initialize empty state"""
        self.timestamp = None
        self.use_nest = None
        self.armed = None
        self.flight_regime = None
        self.actuation_mode = None
        self.set_monitors = []
        self.overridden_monitors = []
        self.captured = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging"""
        return {
            'timestamp': self.timestamp,
            'use_nest': self.use_nest,
            'armed': self.armed,
            'flight_regime': self.flight_regime,
            'actuation_mode': self.actuation_mode,
            'set_monitors': self.set_monitors.copy(),
            'overridden_monitors': self.overridden_monitors.copy()
        }
    
    def __repr__(self) -> str:
        return f"UUTState(mode={self.actuation_mode}, armed={self.armed}, regime={self.flight_regime}, captured={self.captured})"
    
    def format_display(self) -> str:
        """
        Format for console display.
        
        Returns:
            Multi-line string with formatted state
        """
        mode_str = get_mode_name(self.actuation_mode) if self.actuation_mode is not None else "UNKNOWN"
        regime_str = get_flight_regime_name(self.flight_regime) if self.flight_regime is not None else "UNKNOWN"
        
        return (
            "┌────────────────────────────────────────┐\n"
            f"│ USE_NEST:        {self.use_nest} ({'ENABLED' if self.use_nest == USE_NEST_ENABLED else 'DISABLED'})       │\n"
            f"│ Armed:           {self.armed}                       │\n"
            f"│ Flight Regime:   {self.flight_regime} ({regime_str})      │\n"
            f"│ Actuation Mode:  {self.actuation_mode} ({mode_str})      │\n"
            f"│ SET Monitors:    {len(self.set_monitors)} monitor(s)              │\n"
            f"│ Overridden:      {len(self.overridden_monitors)} monitor(s)              │\n"
            "└────────────────────────────────────────┘"
        )
    
    def matches(self, other: UUTState) -> bool:
        """
        Check if this state matches another.
        
        Args:
            other: Another UUTState object
        
        Returns:
            bool: True if states match
        """
        if not isinstance(other, UUTState) or not other.captured:
            return False
        
        return (
            self.use_nest == other.use_nest and
            self.armed == other.armed and
            self.actuation_mode == other.actuation_mode and
            set(self.set_monitors) == set(other.set_monitors) and
            set(self.overridden_monitors) == set(other.overridden_monitors)
        )
    
    def get_differences(self, other: UUTState) -> List[str]:
        """
        Get list of differences between this state and another.
        
        Args:
            other: Another UUTState object
        
        Returns:
            List of difference strings
        """
        diffs = []
        
        if not other.captured:
            return ["Final state could not be captured."]
        
        if self.use_nest != other.use_nest:
            diffs.append(f"USE_NEST: expected {self.use_nest}, got {other.use_nest}")
        
        if self.armed != other.armed:
            diffs.append(f"Armed: expected {self.armed}, got {other.armed}")
        
        if self.actuation_mode != other.actuation_mode:
            diffs.append(
                f"Actuation Mode: expected {self.actuation_mode}, "
                f"got {other.actuation_mode}"
            )
        
        set_diff = set(self.set_monitors).symmetric_difference(set(other.set_monitors))
        if set_diff:
            diffs.append(f"SET Monitors differ: {sorted(list(set_diff))}")
        
        ovr_diff = set(self.overridden_monitors).symmetric_difference(
            set(other.overridden_monitors)
        )
        if ovr_diff:
            diffs.append(f"Overridden Monitors differ: {sorted(list(ovr_diff))}")
        
        return diffs

def connect_to_vehicle(ip_address: str, port: int, timeout: float = 10.0) -> Any:
    """
    Connect to vehicle via MAVLink UDP with input validation.
    
    Args:
        ip_address: Vehicle IP address (must be valid IPv4/IPv6)
        port: MAVLink port (1-65535, typically 13002)
        timeout: Connection timeout in seconds (must be positive)
    
    Returns:
        MAVLink master connection object
    
    Raises:
        ValueError: If inputs are invalid
        TypeError: If inputs have wrong type
        Exception: If connection fails
    """
    # Validate IP address
    if not isinstance(ip_address, str):
        raise TypeError(f"ip_address must be str, got {type(ip_address)}")
    
    # SITL mode: RR_SITL_MODE=1 in environment enables loopback + udpout.
    # This is set only by test/sim launchers (ws_server.py --sitl, run_sim.py).
    # Production never sets this env var.
    _sitl_mode = os.environ.get("RR_SITL_MODE") == "1"

    try:
        ip = ipaddress.ip_address(ip_address)
        validated_ip = str(ip)  # Normalize

        # Security: Reject loopback and multicast only
        # NOTE: Do NOT reject is_reserved — Python marks RFC-1918 private ranges
        # (e.g. 172.16-31.x.x used by Roadrunner vehicles) as reserved on some
        # Python versions, which would incorrectly block valid vehicle IPs.
        if ip.is_loopback and not _sitl_mode:
            raise ValueError(
                "Loopback addresses (127.x.x.x, ::1) not allowed for vehicle connection"
            )
        if ip.is_multicast:
            raise ValueError("Multicast addresses not allowed")

    except ValueError as e:
        raise ValueError(f"Invalid IP address '{ip_address}': {e}")
    
    # Validate port
    if not isinstance(port, int):
        raise TypeError(f"port must be int, got {type(port)}")
    if not (1 <= port <= 65535):
        raise ValueError(f"port must be 1-65535, got {port}")
    
    # Validate timeout
    if not isinstance(timeout, (int, float)):
        raise TypeError(f"timeout must be number, got {type(timeout)}")
    if timeout <= 0:
        raise ValueError(f"timeout must be positive, got {timeout}")
    
    # Add dialect directory to Python path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    dialect_dir = os.path.join(script_dir, "dialects")
    
    if dialect_dir not in sys.path:
        sys.path.insert(0, dialect_dir)
    
    # SITL mode uses udpout: (sim listens on udpin). Production uses udpin:.
    connection_string = (
        f"udpout:{validated_ip}:{port}" if _sitl_mode
        else f"udpin:{validated_ip}:{port}"
    )

    try:
        master = mavutil.mavlink_connection(
            connection_string,
            dialect="pandion_vehicle_roadrunner",
            source_system=255,
            source_component=190
        )
    except Exception as e:
        raise Exception(f"Failed to create MAVLink connection: {type(e).__name__}: {str(e)}")

    # In SITL mode, send heartbeat bursts to "kick" the sim into responding
    # (udpout: needs to send first before sim knows where to reply).
    if _sitl_mode:
        import time as _time
        deadline = _time.monotonic() + timeout
        while _time.monotonic() < deadline:
            try:
                master.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_GCS,
                    mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                    0, 0, mavutil.mavlink.MAV_STATE_ACTIVE,
                )
            except OSError:
                pass  # Windows WSAECONNRESET — safe to retry
            hb = master.recv_match(type="HEARTBEAT", blocking=True, timeout=1.0)
            if hb and hb.get_srcSystem() != 255:
                return master
        raise Exception(
            f"Connection timeout after {timeout}s - "
            f"no heartbeat from {validated_ip}:{port}"
        )

    # Production: wait for heartbeat
    heartbeat_received = master.wait_heartbeat(timeout=timeout)
    
    if not heartbeat_received:
        raise Exception(
            f"Connection timeout after {timeout}s - no heartbeat received from {validated_ip}:{port}"
        )
    
    return master