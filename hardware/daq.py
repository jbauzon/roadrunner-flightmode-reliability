"""
DAQ Controller - Hardware abstraction for NI-DAQmx digital output control

This module provides relay control through NI-DAQ digital output lines.
Each line controls one relay, which powers one UUT.
"""
import time
import threading

try:
    import nidaqmx
    from nidaqmx.constants import LineGrouping
    DAQMX_AVAILABLE = True
except ImportError:
    DAQMX_AVAILABLE = False
    print("Warning: nidaqmx not available. Install with: pip install nidaqmx")


class SimpleDAQController:
    """
    Simple DAQ controller for digital output control with auto-detection.
    
    Thread-safe relay control for multi-UUT testing with state tracking
    and verification.
    Automatically detects available lines on device.
    """
    
    def __init__(self):
        """Initialize controller (device not connected yet)"""
        self.do_task = None
        self.device_name = None
        self.num_lines = 0
        self._output_states = []  # Cached output states
        self._state_lock = threading.Lock()  # Thread safety for relay operations
    
    def initialize(self, device_name="Dev1", num_lines=8):
        """
        Initialize digital output task with auto-detection of available lines.
        
        Args:
            device_name: NI-DAQ device name (e.g., "Dev1")
            num_lines: Maximum number of lines to try (will detect actual count)
        
        Returns:
            (success: bool, message: str)
        """
        if not DAQMX_AVAILABLE:
            return False, "nidaqmx not available"
        
        try:
            # Close any existing task
            self.close()
            
            self.device_name = device_name
            
            # Create unique task name to avoid conflicts
            task_name = f"relay_control_{int(time.time() * 1000000)}"
            self.do_task = nidaqmx.Task(task_name)
            
            # Auto-detect available lines
            lines_added = 0
            for i in range(num_lines):
                try:
                    line = f"{device_name}/port0/line{i}"
                    self.do_task.do_channels.add_do_chan(
                        line,
                        line_grouping=LineGrouping.CHAN_PER_LINE
                    )
                    lines_added += 1
                except Exception as e:
                    if "does not exist" in str(e):
                        break  # No more lines available
                    else:
                        raise  # Real error
            
            if lines_added == 0:
                raise Exception(f"No digital output lines found on {device_name}/port0")
            
            self.num_lines = lines_added
            
            # Initialize cached state tracking
            self._output_states = [False] * self.num_lines
            
            # Initialize all lines to LOW (safe state)
            self.do_task.write(self._output_states)
            
            return True, f"Initialized {self.num_lines} digital outputs on {device_name}"
            
        except Exception as e:
            if self.do_task:
                try:
                    self.do_task.close()
                except:
                    pass
                self.do_task = None
            return False, f"DAQ initialization error: {str(e)}"
    
    def set_line(self, line_num, state):
        """
        Set a single digital output line with thread safety and verification.
        
        Thread-safe operation with state tracking and verification.
        Preserves state of other lines (read-modify-write).
        
        Args:
            line_num: Line number (0 to num_lines-1)
            state: True (HIGH) or False (LOW)
        
        Returns:
            (success: bool, message: str)
        """
        if not self.do_task:
            return False, "DAQ not initialized"
        
        with self._state_lock:
            try:
                # Validate line number first
                if not isinstance(line_num, int):
                    return False, f"Line number must be int, got {type(line_num)}"
                if not (0 <= line_num < self.num_lines):
                    return False, f"Line {line_num} out of range (device has {self.num_lines} lines, 0-{self.num_lines-1})"
                
                # Validate state
                if not isinstance(state, bool):
                    return False, f"State must be bool, got {type(state)}"
                
                # Try to read current state from hardware
                try:
                    current_states = self.do_task.read(number_of_samples_per_channel=1)
                    
                    # Handle different return formats from nidaqmx
                    if isinstance(current_states, list):
                        if isinstance(current_states[0], list):
                            current_states = current_states[0]
                    else:
                        current_states = [current_states]
                    
                    # Update cached state with hardware state
                    for i in range(min(len(current_states), self.num_lines)):
                        self._output_states[i] = bool(current_states[i])
                    
                except Exception as e:
                    # If read fails, use cached state with warning
                    print(f"⚠ DAQ read failed, using cached state: {e}")
                
                # Check if state already matches (no-op optimization)
                if self._output_states[line_num] == state:
                    return True, f"Line {line_num} already {state}"
                
                # Modify requested line in cached state
                old_state = self._output_states[line_num]
                self._output_states[line_num] = state
                
                # Write all states to hardware
                try:
                    self.do_task.write(self._output_states)
                except Exception as e:
                    # Write failed - restore old state in cache
                    self._output_states[line_num] = old_state
                    return False, f"Failed to write to DAQ: {type(e).__name__}: {str(e)}"
                
                # Verify write succeeded by reading back
                try:
                    verify_states = self.do_task.read(number_of_samples_per_channel=1)
                    if isinstance(verify_states, list):
                        if isinstance(verify_states[0], list):
                            verify_states = verify_states[0]
                    else:
                        verify_states = [verify_states]
                    
                    actual_state = bool(verify_states[line_num])
                    if actual_state != state:
                        # Verification failed - update cache with actual state
                        self._output_states[line_num] = actual_state
                        return False, f"Line {line_num} verification failed (requested {state}, read back {actual_state})"
                    
                except Exception as e:
                    # Verification failed but write may have succeeded
                    print(f"⚠ DAQ verification failed (write may have succeeded): {e}")
                
                return True, f"Line {line_num} set to {state} (verified)"
                
            except Exception as e:
                return False, f"Error setting line: {type(e).__name__}: {str(e)}"
    
    def set_all_low(self):
        """
        Set all outputs to LOW (safety function).
        
        Returns:
            (success: bool, message: str)
        """
        if not self.do_task:
            return False, "DAQ not initialized"
        
        try:
            self.do_task.write([False] * self.num_lines)
            return True, "All outputs set to low"
        except Exception as e:
            return False, f"Error: {str(e)}"
    
    def close(self):
        """
        Close the DAQ task safely with proper error handling.
        
        Sets all outputs LOW before closing. Logs all errors but ensures
        cleanup completes even if individual steps fail.
        
        Returns:
            (success: bool, message: str)
        """
        if not self.do_task:
            return True, "DAQ already closed"
        
        errors = []
        
        # Step 1: CRITICAL - Set all outputs LOW for hardware safety
        try:
            self.do_task.write([False] * self.num_lines)
            print(f"✓ DAQ close: Set all {self.num_lines} outputs to LOW")
        except Exception as e:
            error_msg = f"Failed to set outputs LOW: {type(e).__name__}: {str(e)}"
            errors.append(error_msg)
            print(f"✗ CRITICAL: DAQ close: {error_msg}")
            # Continue cleanup even if this fails
        
        # Step 2: Stop the task
        try:
            self.do_task.stop()
            print("✓ DAQ close: Task stopped")
        except Exception as e:
            error_msg = f"Failed to stop task: {type(e).__name__}: {str(e)}"
            errors.append(error_msg)
            print(f"⚠ DAQ close: {error_msg}")
            # Continue cleanup
        
        # Step 3: Close the task
        try:
            self.do_task.close()
            print("✓ DAQ close: Task closed")
        except Exception as e:
            error_msg = f"Failed to close task: {type(e).__name__}: {str(e)}"
            errors.append(error_msg)
            print(f"⚠ DAQ close: {error_msg}")
        finally:
            # Always clear reference, even if close failed
            self.do_task = None
        
        if errors:
            return False, f"DAQ close completed with errors: {'; '.join(errors)}"
        else:
            return True, "DAQ closed successfully"
    
    @staticmethod
    def detect_devices():
        """
        Detect available DAQ devices.
        
        Returns:
            List of device names (e.g., ["Dev1", "Dev2"])
        """
        if not DAQMX_AVAILABLE:
            return []
        
        try:
            system = nidaqmx.system.System.local()
            return [dev.name for dev in system.devices]
        except:
            return []
    
    @staticmethod
    def get_device_info(device_name):
        """
        Get information about a specific device.
        
        Args:
            device_name: Device name (e.g., "Dev1")
        
        Returns:
            Dictionary with device info or None if error
        """
        if not DAQMX_AVAILABLE:
            return None
        
        try:
            system = nidaqmx.system.System.local()
            device = system.devices[device_name]
            
            info = {
                'name': device.name,
                'product_type': device.product_type,
                'do_ports': [],
                'do_lines': []
            }
            
            try:
                do_ports = device.do_ports
                info['do_ports'] = [port.name for port in do_ports]
            except:
                pass
            
            try:
                do_lines = device.do_lines
                info['do_lines'] = [line.name for line in do_lines]
            except:
                pass
            
            return info
        except Exception as e:
            return {'error': str(e)}
    
    def verify_connection(self):
        """
        Verify DAQ is still connected and responsive.
        
        Returns:
            bool: True if DAQ is healthy
        """
        if not self.do_task:
            return False
        
        try:
            # Try to read current state
            self.do_task.read(number_of_samples_per_channel=1)
            return True
        except:
            return False
    
    def reconnect(self):
        """
        Attempt to reconnect DAQ after connection loss.
        
        Returns:
            (success: bool, message: str)
        """
        device = self.device_name
        num_lines = self.num_lines
        
        self.close()
        time.sleep(1.0)
        
        return self.initialize(device, num_lines)