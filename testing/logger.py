from __future__ import annotations

"""
Telemetry Logger - Descriptive CSV logging for IBIT tests

This module provides human-readable CSV logging with complete test lifecycle:
- Actions done TO the vehicle (commands, relay changes)
- Telemetry FROM the vehicle (actuator feedback, status)
- Complete event descriptions
- Daily log rotation
"""
import os
import csv
import sys
import time
from datetime import datetime
from typing import Any, Optional

from vehicle.constants import (
    TestMode, FLIGHT_REGIME_NAMES, ACTUATION_MODE_NAMES, SEVERITY_NAMES,
    DEFAULT_ACTUATOR_POSITION_CDEG, IBITSubstate,
    get_flight_regime_name, get_severity_name, is_armed,
)


class TelemetryLogger:
    """
    IBIT-focused telemetry logger with human-readable, descriptive CSV format.

    Logs both test control events and vehicle telemetry with context.
    Supports both IBIT and Flight Profile Playback test modes.
    """

    MODE_IBIT_FOCUSED = "ibit_focused"
    MODE_NONE = "none"

    def __init__(self, log_directory: str, uut_serial: str, test_start_datetime: Any,
                 logging_mode: str = MODE_IBIT_FOCUSED, max_file_size_mb: int = 100,
                 test_mode: str = 'ibit',
                 on_log=None, on_file_rotated=None) -> None:
        """
        Initialize telemetry logger.

        Args:
            log_directory: Base directory for logs
            uut_serial: UUT serial number
            test_start_datetime: When batch test started (datetime)
            logging_mode: Logging mode (IBIT_FOCUSED or NONE)
            max_file_size_mb: Maximum file size before rotation
            test_mode: 'ibit' or 'playback' — affects log filename
            on_log: Callback for log messages (str) -> None
            on_file_rotated: Callback for file rotation (str) -> None
        """
        self._on_log = on_log or (lambda msg: None)
        self._on_file_rotated = on_file_rotated or (lambda path: None)
        self.log_directory = log_directory
        self.uut_serial = uut_serial
        self.test_start_datetime = test_start_datetime
        self.logging_mode = logging_mode
        self.max_file_size = max_file_size_mb * 1024 * 1024
        self.test_mode = test_mode
        
        self.current_date = None
        self.current_log_path = None
        self.log_file = None
        self.csv_writer = None
        
        # Descriptive column names with units
        self.ibit_columns = [
            'Date',
            'Time',
            'Timestamp_Seconds',
            'Event_Category',
            'Event_Type',
            'Event_Description',
            'Relay_Status',
            'IBIT_Phase',
            'Vehicle_Armed',
            'Flight_Regime',
            'Actuation_Mode',
            'IBIT_Substate_Number',
            'Left_Elevon_Position_deg',
            'Right_Elevon_Position_deg',
            'Dorsal_Rudder_Position_deg',
            'Ventral_Rudder_Position_deg',
            'Left_TVC_Upper_Position_deg',
            'Left_TVC_Lower_Position_deg',
            'Right_TVC_Upper_Position_deg',
            'Right_TVC_Lower_Position_deg',
            'Left_Elevon_Current_mA',
            'Right_Elevon_Current_mA',
            'Dorsal_Rudder_Current_mA',
            'Ventral_Rudder_Current_mA',
            'Left_TVC_Upper_Current_mA',
            'Left_TVC_Lower_Current_mA',
            'Right_TVC_Upper_Current_mA',
            'Right_TVC_Lower_Current_mA',
            'Left_Elevon_Temp_C',
            'Right_Elevon_Temp_C',
            'Monitors_Active_Count',
            'Monitors_Overridden_Count',
        ]
        
        self.current_file_size = 0
        self.flush_interval = 2.0
        self.last_flush_time = datetime.now().timestamp()  # consistent with log_telemetry
        
        # Track current state
        self.current_ibit_phase = "UNKNOWN"
        self.current_relay_state = "UNKNOWN"
        self.current_armed_state = "UNKNOWN"
        self.current_flight_regime = "UNKNOWN"
        self.current_actuation_mode = "UNKNOWN"
        self.iteration_number = 0
    
    def get_log_path_for_date(self, date_obj: Any) -> str:
        """
        Generate log file path for a specific date.

        Filename includes test mode (IBIT or Playback) so the two can be
        distinguished in the logs folder.

        Args:
            date_obj: Date object

        Returns:
            Full path to log file
        """
        day_num = (date_obj - self.test_start_datetime.date()).days + 1
        day_str = f"day{day_num:02d}"
        date_str = date_obj.strftime('%Y%m%d')
        mode_tag = "IBIT" if self.test_mode == TestMode.IBIT else "Playback"
        filename = (
            f"UUT_{self.uut_serial}_{day_str}_{date_str}_{mode_tag}_Test.csv"
        )
        return os.path.join(self.log_directory, filename)
    
    def open(self) -> bool:
        """
        Open log file for current date.
        
        Creates new file or appends to existing.
        Writes header for new files.
        
        Returns:
            bool: Success
        """
        try:
            if self.logging_mode == self.MODE_NONE:
                return True
            
            current_date = datetime.now().date()
            
            # Check if we need to rotate to new day
            if self.current_date != current_date:
                if self.log_file:
                    self.log_file.flush()
                    self.log_file.close()
                    self._on_log(
                        f"📁 Closed log file: {os.path.basename(self.current_log_path)}"
                    )
                
                self.current_date = current_date
                self.current_log_path = self.get_log_path_for_date(current_date)

                # Ensure log directory exists (handles relative paths, ui/ context)
                os.makedirs(os.path.dirname(self.current_log_path), exist_ok=True)

                file_exists = os.path.exists(self.current_log_path)
                
                self.log_file = open(
                    self.current_log_path,
                    'a',
                    newline='',
                    encoding='utf-8'
                )
                self.csv_writer = csv.writer(self.log_file)
                
                # Write header only for new files
                if not file_exists:
                    self.csv_writer.writerow(self.ibit_columns)
                    self._on_log(f"📁 Created descriptive IBIT test log")
                else:
                    self._on_log(f"📁 Appending to IBIT test log")
                
                self.current_file_size = self.log_file.tell()
            
            return True
            
        except Exception as e:
            self._on_log(f"Error opening log file: {e}")
            return False
    
    def log_test_event(self, event_type: str, description: str) -> None:
        """
        Log a test lifecycle event.
        
        Args:
            event_type: Type of event (e.g., 'ITERATION_START', 'ARM_REQUEST')
            description: Human-readable description
        """
        if self.logging_mode == self.MODE_NONE or not self.log_file:
            return
        
        try:
            now = datetime.now()
            timestamp = now.timestamp()
            
            row = {col: '' for col in self.ibit_columns}
            row['Date'] = now.strftime('%Y-%m-%d')
            row['Time'] = now.strftime('%H:%M:%S.%f')[:-3]
            row['Timestamp_Seconds'] = f"{timestamp:.3f}"
            row['Event_Category'] = 'TEST_CONTROL'
            row['Event_Type'] = event_type
            row['Event_Description'] = description
            row['Relay_Status'] = self.current_relay_state
            row['IBIT_Phase'] = self.current_ibit_phase
            row['Vehicle_Armed'] = self.current_armed_state
            row['Flight_Regime'] = self.current_flight_regime
            row['Actuation_Mode'] = self.current_actuation_mode
            
            self._write_row(row)
            
        except Exception as e:
            self._on_log(f"Error logging test event: {e}")
    
    def log_relay_state(self, relay_line: str, state: bool) -> None:
        """
        Log relay state change.
        
        Args:
            relay_line: Relay line number
            state: True (ON) or False (OFF)
        """
        if self.logging_mode == self.MODE_NONE or not self.log_file:
            return
        
        try:
            self.current_relay_state = "ON" if state else "OFF"
            now = datetime.now()
            
            description = f"Power relay #{relay_line} turned {self.current_relay_state}"
            if state:
                description += " - Vehicle powered ON, starting test"
            else:
                description += " - Vehicle powered OFF, test complete"
            
            row = {col: '' for col in self.ibit_columns}
            row['Date'] = now.strftime('%Y-%m-%d')
            row['Time'] = now.strftime('%H:%M:%S.%f')[:-3]
            row['Timestamp_Seconds'] = f"{now.timestamp():.3f}"
            row['Event_Category'] = 'TEST_CONTROL'
            row['Event_Type'] = f'RELAY_{"ON" if state else "OFF"}'
            row['Event_Description'] = description
            row['Relay_Status'] = self.current_relay_state
            row['IBIT_Phase'] = self.current_ibit_phase
            row['Vehicle_Armed'] = self.current_armed_state
            row['Flight_Regime'] = self.current_flight_regime
            row['Actuation_Mode'] = self.current_actuation_mode
            
            self._write_row(row)
            
        except Exception as e:
            self._on_log(f"Error logging relay state: {e}")
    
    def set_iteration_number(self, iteration: int) -> None:
        """Set current iteration number"""
        self.iteration_number = iteration
    
    def update_ibit_phase(self, substate: int) -> None:
        """
        Update current IBIT phase.
        
        Args:
            substate: IBIT substate number (0-5)
        """
        phase_map = {
            IBITSubstate.BEGIN: "BEGIN (Initializing)",
            IBITSubstate.WAIT_FOR_SETTLE: "WAIT_FOR_SETTLE (Waiting for stabilization)",
            IBITSubstate.ELEVONS: "ELEVONS (Testing wing controls)",
            IBITSubstate.RUDDERS: "RUDDERS (Testing tail controls)",
            IBITSubstate.TVC: "TVC (Testing engine gimbals)",
            IBITSubstate.COMPLETE: "COMPLETE (All tests passed)"
        }
        
        old_phase = self.current_ibit_phase
        self.current_ibit_phase = phase_map.get(substate, f"UNKNOWN_STATE_{substate}")
        
        # Log phase transition
        if old_phase != self.current_ibit_phase and old_phase != "UNKNOWN":
            self.log_test_event(
                'PHASE_TRANSITION',
                f"IBIT phase changed: {old_phase.split('(')[0].strip()} → "
                f"{self.current_ibit_phase.split('(')[0].strip()}"
            )
    
    def update_armed_state(self, armed: bool, flight_regime: int) -> None:
        """
        Update armed state and flight regime.
        
        Args:
            armed: True if vehicle is armed
            flight_regime: Flight regime number
        """
        old_armed_state = self.current_armed_state
        self.current_armed_state = 'YES (ARMED!)' if armed else 'NO (Safe)'
        self.current_flight_regime = (
            f"{flight_regime} ({get_flight_regime_name(flight_regime)})"
        )
        
        # Log if armed state changed
        if old_armed_state != self.current_armed_state and old_armed_state != "UNKNOWN":
            self.log_test_event(
                'ARMED_STATE_CHANGE',
                f"Vehicle {'ARMED - motors can spin!' if armed else 'DISARMED - safe state'} "
                f"(Flight Regime: {self.current_flight_regime})"
            )
    
    def log_telemetry(self, msg: Any) -> None:
        """
        Log telemetry with descriptive context.
        
        Args:
            msg: MAVLink message object
        """
        if self.logging_mode == self.MODE_NONE or not self.log_file:
            return
        
        try:
            # Check for date change
            current_date = datetime.now().date()
            if self.current_date != current_date:
                self.open()
            
            msg_type = msg.get_type()
            now = datetime.now()
            
            # Log actuation status
            if msg_type == 'PANDION_RR_ACTUATION_SYS_STATUS':
                row = {col: '' for col in self.ibit_columns}
                row['Date'] = now.strftime('%Y-%m-%d')
                row['Time'] = now.strftime('%H:%M:%S.%f')[:-3]
                row['Timestamp_Seconds'] = f"{now.timestamp():.3f}"
                row['Event_Category'] = 'VEHICLE_DATA'
                row['Event_Type'] = 'ACTUATOR_FEEDBACK'
                
                # Update phase tracking
                if hasattr(msg, 'actuation_ibit_substate'):
                    substate = msg.actuation_ibit_substate
                    self.update_ibit_phase(substate)
                    row['IBIT_Substate_Number'] = substate
                
                row['IBIT_Phase'] = self.current_ibit_phase
                row['Relay_Status'] = self.current_relay_state
                
                # Actuation mode
                mode = msg.actuation_state
                mode_name = ACTUATION_MODE_NAMES.get(mode, f"UNKNOWN_{mode}")
                self.current_actuation_mode = mode_name
                row['Actuation_Mode'] = self.current_actuation_mode
                
                row['Vehicle_Armed'] = self.current_armed_state
                row['Flight_Regime'] = self.current_flight_regime
                
                # Actuator positions (centidegrees to degrees)
                row['Left_Elevon_Position_deg'] = (
                    f"{getattr(msg, 'left_elevon_feedback_cdeg', DEFAULT_ACTUATOR_POSITION_CDEG) / 100.0:.2f}"
                )
                row['Right_Elevon_Position_deg'] = (
                    f"{getattr(msg, 'right_elevon_feedback_cdeg', DEFAULT_ACTUATOR_POSITION_CDEG) / 100.0:.2f}"
                )
                row['Dorsal_Rudder_Position_deg'] = (
                    f"{getattr(msg, 'dorsal_rudder_feedback_cdeg', DEFAULT_ACTUATOR_POSITION_CDEG) / 100.0:.2f}"
                )
                row['Ventral_Rudder_Position_deg'] = (
                    f"{getattr(msg, 'ventral_rudder_feedback_cdeg', DEFAULT_ACTUATOR_POSITION_CDEG) / 100.0:.2f}"
                )
                row['Left_TVC_Upper_Position_deg'] = (
                    f"{getattr(msg, 'left_tvc_upper_feedback_cdeg', DEFAULT_ACTUATOR_POSITION_CDEG) / 100.0:.2f}"
                )
                row['Left_TVC_Lower_Position_deg'] = (
                    f"{getattr(msg, 'left_tvc_lower_feedback_cdeg', DEFAULT_ACTUATOR_POSITION_CDEG) / 100.0:.2f}"
                )
                row['Right_TVC_Upper_Position_deg'] = (
                    f"{getattr(msg, 'right_tvc_upper_feedback_cdeg', DEFAULT_ACTUATOR_POSITION_CDEG) / 100.0:.2f}"
                )
                row['Right_TVC_Lower_Position_deg'] = (
                    f"{getattr(msg, 'right_tvc_lower_feedback_cdeg', DEFAULT_ACTUATOR_POSITION_CDEG) / 100.0:.2f}"
                )
                
                # Currents
                row['Left_Elevon_Current_mA'] = getattr(msg, 'left_elevon_current_mA', '')
                row['Right_Elevon_Current_mA'] = getattr(msg, 'right_elevon_current_mA', '')
                row['Dorsal_Rudder_Current_mA'] = getattr(msg, 'dorsal_rudder_current_mA', '')
                row['Ventral_Rudder_Current_mA'] = getattr(msg, 'ventral_rudder_current_mA', '')
                row['Left_TVC_Upper_Current_mA'] = getattr(msg, 'left_tvc_upper_current_mA', '')
                row['Left_TVC_Lower_Current_mA'] = getattr(msg, 'left_tvc_lower_current_mA', '')
                row['Right_TVC_Upper_Current_mA'] = getattr(msg, 'right_tvc_upper_current_mA', '')
                row['Right_TVC_Lower_Current_mA'] = getattr(msg, 'right_tvc_lower_current_mA', '')
                
                # Temperatures
                row['Left_Elevon_Temp_C'] = getattr(msg, 'left_elevon_motor_temp_degC', '')
                row['Right_Elevon_Temp_C'] = getattr(msg, 'right_elevon_motor_temp_degC', '')
                
                # Description
                phase_short = self.current_ibit_phase.split('(')[0].strip()
                row['Event_Description'] = (
                    f"Actuator feedback during {phase_short} phase "
                    f"(iteration {self.iteration_number})"
                )
                
                self._write_row(row)
            
            # Log PANDION_STATUS for armed status and flight regime
            elif msg_type == 'PANDION_STATUS':
                flight_regime = msg.flight_regime
                armed = is_armed(flight_regime)
                
                # Update internal state
                old_armed = self.current_armed_state
                self.update_armed_state(armed, flight_regime)
                
                # Only log if state changed
                if old_armed != self.current_armed_state and old_armed != "UNKNOWN":
                    row = {col: '' for col in self.ibit_columns}
                    row['Date'] = now.strftime('%Y-%m-%d')
                    row['Time'] = now.strftime('%H:%M:%S.%f')[:-3]
                    row['Timestamp_Seconds'] = f"{now.timestamp():.3f}"
                    row['Event_Category'] = 'SYSTEM_STATUS'
                    row['Event_Type'] = 'ARMED_STATE_CHANGE'
                    row['Vehicle_Armed'] = self.current_armed_state
                    row['Flight_Regime'] = self.current_flight_regime
                    row['Relay_Status'] = self.current_relay_state
                    row['IBIT_Phase'] = self.current_ibit_phase
                    row['Actuation_Mode'] = self.current_actuation_mode
                    row['Event_Description'] = (
                        f"Vehicle {'ARMED - motors can spin!' if armed else 'DISARMED - safe state'} "
                        f"(Flight Regime: {self.current_flight_regime})"
                    )
                    
                    self._write_row(row)
            
            # Log monitor status
            elif msg_type == 'PANDION_MONITOR_CURRENT_STATUS':
                monitors_set = self._count_set_monitors(msg.currently_set)
                monitors_overridden = self._count_set_monitors(msg.currently_overridden)
                
                row = {col: '' for col in self.ibit_columns}
                row['Date'] = now.strftime('%Y-%m-%d')
                row['Time'] = now.strftime('%H:%M:%S.%f')[:-3]
                row['Timestamp_Seconds'] = f"{now.timestamp():.3f}"
                row['Event_Category'] = 'SYSTEM_STATUS'
                row['Event_Type'] = 'SAFETY_MONITORS'
                row['Monitors_Active_Count'] = monitors_set
                row['Monitors_Overridden_Count'] = monitors_overridden
                row['Relay_Status'] = self.current_relay_state
                row['IBIT_Phase'] = self.current_ibit_phase
                row['Vehicle_Armed'] = self.current_armed_state
                row['Flight_Regime'] = self.current_flight_regime
                row['Actuation_Mode'] = self.current_actuation_mode
                
                if monitors_set > 0:
                    row['Event_Description'] = (
                        f"⚠️ {monitors_set} safety warning(s) active, "
                        f"{monitors_overridden} overridden"
                    )
                else:
                    row['Event_Description'] = (
                        f"✓ All safety checks passing "
                        f"({monitors_overridden} monitors overridden for testing)"
                    )
                
                self._write_row(row)
            
            # Log status text messages
            elif msg_type == 'STATUSTEXT':
                row = {col: '' for col in self.ibit_columns}
                row['Date'] = now.strftime('%Y-%m-%d')
                row['Time'] = now.strftime('%H:%M:%S.%f')[:-3]
                row['Timestamp_Seconds'] = f"{now.timestamp():.3f}"
                row['Event_Category'] = 'SYSTEM_STATUS'
                row['Event_Type'] = 'STATUS_MESSAGE'
                row['Relay_Status'] = self.current_relay_state
                row['IBIT_Phase'] = self.current_ibit_phase
                row['Vehicle_Armed'] = self.current_armed_state
                row['Flight_Regime'] = self.current_flight_regime
                row['Actuation_Mode'] = self.current_actuation_mode
                
                severity = get_severity_name(msg.severity)
                row['Event_Description'] = f"[{severity}] {msg.text}"
                
                self._write_row(row)
            
            # Periodic flush — use consistent datetime source
            if now.timestamp() - self.last_flush_time >= self.flush_interval:
                self.log_file.flush()
                self.current_file_size = self.log_file.tell()
                self.last_flush_time = now.timestamp()
        
        except Exception as e:
            self._on_log(f"Error logging telemetry: {e}")
    
    def _write_row(self, row_dict: dict) -> None:
        """
        Write a row to CSV.
        
        Args:
            row_dict: Dictionary mapping column names to values
        """
        row = [row_dict.get(col, '') for col in self.ibit_columns]
        self.csv_writer.writerow(row)
        self.current_file_size = self.log_file.tell()
    
    def _count_set_monitors(self, byte_array: Any) -> int:
        """
        Count how many monitors are SET.

        Uses bin().count('1') (popcount) — faster and simpler than
        the nested loop approach.

        Args:
            byte_array: Array of bytes representing monitor bits

        Returns:
            int: Number of SET monitors
        """
        return sum(bin(b).count('1') for b in byte_array)
    
    def close(self) -> None:
        """Close log file with proper error handling and logging"""
        if self.log_file:
            errors = []
            
            # Step 1: Flush any pending writes
            try:
                self.log_file.flush()
            except Exception as e:
                error_msg = f"Failed to flush log file: {type(e).__name__}: {str(e)}"
                errors.append(error_msg)
                # Log to stderr since we can't log to the file
                print(f"ERROR: {error_msg}", file=sys.stderr)
            
            # Step 2: Close the file handle
            try:
                self.log_file.close()
            except Exception as e:
                error_msg = f"Failed to close log file: {type(e).__name__}: {str(e)}"
                errors.append(error_msg)
                print(f"ERROR: {error_msg}", file=sys.stderr)
            finally:
                # Always clear reference even if close failed
                self.log_file = None
                self.csv_writer = None
            
            if errors:
                # Emit signal if possible
                try:
                    self._on_log(
                        f"⚠ Log close completed with errors: {'; '.join(errors)}"
                    )
                except Exception:
                    pass
    
    def get_current_log_path(self) -> Optional[str]:
        """Get path to current log file"""
        return self.current_log_path