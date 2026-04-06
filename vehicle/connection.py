"""
Vehicle Connection - MAVLink communication and state management
This module handles low-level MAVLink communication with flight controllers.
Includes UUT definition and state capture classes.
"""
import sys
import os
import ipaddress
from pymavlink import mavutil

class UUT:
    """
    Unit Under Test definition with input validation.
    
    Represents a single flight controller being tested.
    """
    
    MAX_RELAY_LINES = 32  # System maximum relay lines
    
    def __init__(self, serial_number="", ip_address="", port=9985, relay_line=0):
        """
        Initialize UUT with validation.
        
        Args:
            serial_number: Unique identifier for this UUT
            ip_address: Network address of vehicle (must be valid IP)
            port: MAVLink UDP port (1-65535, default: 9985)
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
        self.status = "Ready"
        self.test_start_time = None
        self.test_end_time = None
        self.iterations_completed = 0
        self.log_file = None
    
    def to_dict(self):
        """Convert to dictionary for saving"""
        return {
            'serial_number': self.serial_number,
            'ip_address': self.ip_address,
            'port': self.port,
            'relay_line': self.relay_line
        }
    
    @staticmethod
    def from_dict(data):
        """Create from dictionary"""
        return UUT(
            serial_number=data.get('serial_number', ''),
            ip_address=data.get('ip_address', ''),
            port=data.get('port', 9985),
            relay_line=data.get('relay_line', 0)
        )

class UUTState:
    """
    Captures the complete state of a UUT.
    
    Used for state capture and restoration to ensure vehicle
    returns to original configuration after testing.
    """
    
    def __init__(self):
        """Initialize empty state"""
        self.timestamp = None
        self.use_nest = None
        self.armed = None
        self.flight_regime = None
        self.actuation_mode = None
        self.set_monitors = []
        self.overridden_monitors = []
        self.captured = False
    
    def to_dict(self):
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
    
    def format_display(self):
        """
        Format for console display.
        
        Returns:
            Multi-line string with formatted state
        """
        mode_names = {
            0: "OFF", 1: "IBIT", 2: "OPERATE", 
            3: "MANUAL", 4: "PLAYBACK", 5: "TRIM"
        }
        mode_str = mode_names.get(self.actuation_mode, f"UNKNOWN({self.actuation_mode})")
        
        regime_names = {
            0: "GROUND_DISARMED", 1: "GROUND_ARMED", 2: "AUTO_TAKEOFF",
            3: "HOVER", 4: "FORWARD_TRANSITION", 5: "CRUISE",
            255: "INVALID"
        }
        regime_str = regime_names.get(
            self.flight_regime, 
            f"REGIME_{self.flight_regime}"
        ) if self.flight_regime is not None else "UNKNOWN"
        
        return (
            "┌────────────────────────────────────────┐\n"
            f"│ USE_NEST:        {self.use_nest} ({'ENABLED' if self.use_nest == 1 else 'DISABLED'})       │\n"
            f"│ Armed:           {self.armed}                       │\n"
            f"│ Flight Regime:   {self.flight_regime} ({regime_str})      │\n"
            f"│ Actuation Mode:  {self.actuation_mode} ({mode_str})      │\n"
            f"│ SET Monitors:    {len(self.set_monitors)} monitor(s)              │\n"
            f"│ Overridden:      {len(self.overridden_monitors)} monitor(s)              │\n"
            "└────────────────────────────────────────┘"
        )
    
    def matches(self, other):
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
    
    def get_differences(self, other):
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

def connect_to_vehicle(ip_address, port, timeout=10.0):
    """
    Connect to vehicle via MAVLink UDP with input validation.
    
    Args:
        ip_address: Vehicle IP address (must be valid IPv4/IPv6)
        port: MAVLink port (1-65535, typically 9985)
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
    
    try:
        ip = ipaddress.ip_address(ip_address)
        validated_ip = str(ip)  # Normalize
        
        # Security: Reject loopback and restricted ranges
        if ip.is_loopback:
            raise ValueError("Loopback addresses (127.x.x.x, ::1) not allowed for vehicle connection")
        if ip.is_multicast:
            raise ValueError("Multicast addresses not allowed")
        if ip.is_reserved:
            raise ValueError("Reserved IP addresses not allowed")
        
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
    
    connection_string = f"udpin:{validated_ip}:{port}"
    
    try:
        master = mavutil.mavlink_connection(
            connection_string,
            dialect="pandion_vehicle_roadrunner",
            source_system=255,
            source_component=190
        )
    except Exception as e:
        raise Exception(f"Failed to create MAVLink connection: {type(e).__name__}: {str(e)}")
    
    # Wait for heartbeat
    heartbeat_received = master.wait_heartbeat(timeout=timeout)
    
    if not heartbeat_received:
        raise Exception(
            f"Connection timeout after {timeout}s - no heartbeat received from {validated_ip}:{port}"
        )
    
    return master