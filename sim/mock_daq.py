"""
MockDAQController — Drop-in replacement for SimpleDAQController.

Used during simulation to avoid needing physical NI-DAQmx hardware.
Logs all relay state changes and simulates the power-cycle delay.
"""
import time


class MockDAQController:
    """
    Mimics SimpleDAQController API exactly.
    Replace the real controller by monkey-patching in run_sim.py.
    """

    def __init__(self):
        self.do_task      = None   # Set to truthy after initialize()
        self.num_lines    = 0
        self._line_states = {}
        self._device_name = None
        self._initialized = False
        self._vehicles    = {}     # relay_line -> PandionVehicleSim (for power cycle)

    # ── Static helpers (mirror real DAQ) ──────────────────────────────────────

    @staticmethod
    def detect_devices():
        return ["SimDAQ/Dev0"]

    @staticmethod
    def get_device_info(device_name):
        return {
            'name':     device_name,
            'do_lines': [f"{device_name}/port0/line{i}" for i in range(8)],
            'type':     'simulated',
        }

    # ── Instance methods ──────────────────────────────────────────────────────

    def initialize(self, device_name, num_lines=8):
        self._device_name = device_name
        self.num_lines    = num_lines
        self._line_states = {i: False for i in range(num_lines)}
        self.do_task      = "MOCK_TASK"  # truthy — satisfies the guard in main_window
        self._initialized = True
        print(f"[MockDAQ] Initialized {device_name} with {num_lines} relay lines")
        return True, f"Mock DAQ initialized: {device_name} ({num_lines} lines)"

    def register_vehicle(self, relay_line, vehicle_sim):
        """Register a sim vehicle for power cycle on relay toggle."""
        self._vehicles[relay_line] = vehicle_sim

    def set_line(self, line, state):
        if not self._initialized:
            return False, "DAQ not initialized"
        if not (0 <= line < self.num_lines):
            return False, f"Line {line} out of range (0–{self.num_lines-1})"

        old = self._line_states.get(line, False)
        self._line_states[line] = state

        # Trigger sim power cycle if vehicle is registered
        vehicle = self._vehicles.get(line)
        if vehicle:
            if state and not old:
                vehicle.power_on()
            elif not state and old:
                vehicle.power_off()

        action = "ON " if state else "OFF"
        change = "  (no change)" if old == state else ""
        print(f"[MockDAQ] Relay D{line:02d} → {action}{change}")
        return True, f"Line {line} set to {state}"

    def set_all_low(self):
        for line in range(self.num_lines):
            self._line_states[line] = False
        print("[MockDAQ] ALL relays → OFF (emergency)")
        return True, "All lines set low"

    def verify_connection(self):
        return self._initialized

    def reconnect(self):
        if self._initialized:
            return True, "Mock reconnect OK"
        return False, "Not initialized"

    def close(self):
        if self._initialized:
            self.do_task = None
            print("[MockDAQ] Closed")

    def get_line_state(self, line):
        return self._line_states.get(line, False)

    def get_all_states(self):
        return dict(self._line_states)
