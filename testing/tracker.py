from __future__ import annotations

"""
IBIT phase tracking and test statistics.
"""
import time
from collections import deque
from typing import Any, Dict, List, Optional

from vehicle.constants import IBIT_SUBSTATE_NAMES, IBITSubstate, DEFAULT_HEARTBEAT_TIMEOUT


class IBITPhaseTracker:
    """
    Phase tracking for IBIT test sequence.
    
    IBIT Substates:
    0: BEGIN (initialization)
    1: WAIT_FOR_SETTLE (stabilization)
    2: ELEVONS (wing control test)
    3: RUDDERS (tail control test)
    4: TVC (engine gimbal test)
    5: COMPLETE (all tests passed)
    
    Note: Completion is detected by mode transition IBIT(1) → OPERATE(2),
    not by reaching substate 5 (vehicle may do multiple IBIT runs).
    """
    
    EXPECTED_SEQUENCE = [
        'WAIT_FOR_SETTLE',
        'ELEVONS',
        'RUDDERS',
        'TVC'
    ]

    EXPECTED_PHASES = EXPECTED_SEQUENCE  # Alias for external callers
    
    def __init__(self) -> None:
        """Initialize tracker"""
        self.phases_completed: List[str] = []
        self.last_substate: Optional[int] = None
        self.current_substate: Optional[int] = None
        self.phase_start_times: Dict[str, float] = {}
        self.phase_durations: Dict[str, float] = {}
        self.last_progress_time: float = time.time()
        self.reached_complete: bool = False
        self.transition_history: List[Dict[str, Any]] = []
    
    def update(self, substate: int, now: float = 0.0) -> None:
        """
        Update tracker with current substate.
        
        Args:
            substate: Current IBIT substate (0-5)
            now: Current time (seconds). If 0.0, time.time() is called internally.
        """
        if now == 0.0:
            now = time.time()
        if substate != self.last_substate:
            self.transition_history.append({
                'from': self.last_substate,
                'to': substate,
                'timestamp': now
            })
            
            # Track phase transitions
            if substate == IBITSubstate.WAIT_FOR_SETTLE:
                self._start_phase('WAIT_FOR_SETTLE', now)
            elif substate == IBITSubstate.ELEVONS:
                self._complete_phase('WAIT_FOR_SETTLE', now)
                self._start_phase('ELEVONS', now)
            elif substate == IBITSubstate.RUDDERS:
                self._complete_phase('ELEVONS', now)
                self._start_phase('RUDDERS', now)
            elif substate == IBITSubstate.TVC:
                self._complete_phase('RUDDERS', now)
                self._start_phase('TVC', now)
            elif substate == IBITSubstate.COMPLETE:
                self._complete_phase('TVC', now)
                self.reached_complete = True
                self.last_progress_time = now
            
            self.last_substate = substate
        
        self.current_substate = substate
    
    def _start_phase(self, phase_name: str, now: float = 0.0) -> None:
        """Record phase start time"""
        if now == 0.0:
            now = time.time()
        if phase_name not in self.phase_start_times:
            self.phase_start_times[phase_name] = now
            self.last_progress_time = now
    
    def _complete_phase(self, phase_name: str, now: float = 0.0) -> None:
        """Record phase completion"""
        if now == 0.0:
            now = time.time()
        if phase_name not in self.phases_completed:
            self.phases_completed.append(phase_name)
            
            if phase_name in self.phase_start_times:
                duration = now - self.phase_start_times[phase_name]
                self.phase_durations[phase_name] = duration
            
            self.last_progress_time = now
    
    def is_complete(self) -> bool:
        """Check if IBIT reached COMPLETE state (substate 5)"""
        return self.reached_complete and self.current_substate == IBITSubstate.COMPLETE
    
    def get_progress(self) -> float:
        """Get test progress (0.0 to 1.0)"""
        if self.reached_complete:
            return 1.0
        return len(self.phases_completed) / len(self.EXPECTED_SEQUENCE)
    
    def time_since_last_progress(self, now: float = 0.0) -> float:
        """Time since last progress in seconds.
        
        Args:
            now: Current time (seconds). If 0.0, time.time() is called internally.
        """
        if now == 0.0:
            now = time.time()
        return now - self.last_progress_time
    
    def get_current_phase_name(self) -> str:
        """Get name of current phase"""
        return IBIT_SUBSTATE_NAMES.get(self.current_substate, "UNKNOWN")
    
    def get_summary(self) -> Dict[str, Any]:
        """Get progress summary"""
        return {
            'current_phase': self.get_current_phase_name(),
            'current_substate': self.current_substate,
            'phases_completed': self.phases_completed,
            'reached_complete': self.reached_complete,
            'progress_percent': self.get_progress() * 100,
            'phase_durations': self.phase_durations.copy(),
            'transition_count': len(self.transition_history)
        }

    def __repr__(self) -> str:
        return (
            f"IBITPhaseTracker(phase={self.get_current_phase_name()}, "
            f"completed={self.phases_completed}, "
            f"complete={self.reached_complete})"
        )


class TestStatistics:
    """Tracks real-time test statistics"""
    
    def __init__(self) -> None:
        """Initialize statistics"""
        self.commands_sent = 0
        self.telemetry_received = 0
        self.heartbeats_received = 0
        self.last_heartbeat_time = 0
        self.communication_errors = 0
        self.iteration_times = deque(maxlen=20)
        self.telemetry_rate_history = deque(maxlen=60)
        self.start_time = time.time()
        self.last_telemetry_count = 0
        self.last_rate_update = time.time()
    
    def record_command_sent(self) -> None:
        """Record a command was sent"""
        self.commands_sent += 1
    
    def record_telemetry_received(self) -> None:
        """Record telemetry message received"""
        self.telemetry_received += 1
    
    def record_heartbeat(self) -> None:
        """Record heartbeat received"""
        self.heartbeats_received += 1
        self.last_heartbeat_time = time.time()
    
    def record_communication_error(self) -> None:
        """Record communication error"""
        self.communication_errors += 1
    
    def record_iteration_time(self, duration: float) -> None:
        """Record iteration completion time"""
        self.iteration_times.append(duration)
    
    def get_average_iteration_time(self) -> float:
        """Get average iteration time"""
        if not self.iteration_times:
            return 0.0
        return sum(self.iteration_times) / len(self.iteration_times)
    
    def update_telemetry_rate(self) -> None:
        """Update telemetry rate calculation"""
        now = time.time()
        if now - self.last_rate_update >= 1.0:
            rate = self.telemetry_received - self.last_telemetry_count
            self.telemetry_rate_history.append(rate)
            self.last_telemetry_count = self.telemetry_received
            self.last_rate_update = now
    
    def get_current_telemetry_rate(self) -> int:
        """Get current telemetry rate (messages/sec)"""
        if not self.telemetry_rate_history:
            return 0
        return self.telemetry_rate_history[-1]
    
    def get_average_telemetry_rate(self) -> float:
        """Get average telemetry rate"""
        if not self.telemetry_rate_history:
            return 0
        return sum(self.telemetry_rate_history) / len(self.telemetry_rate_history)
    
    def time_since_last_heartbeat(self) -> float:
        """Time since last heartbeat in seconds"""
        if self.last_heartbeat_time == 0:
            return float('inf')
        return time.time() - self.last_heartbeat_time
    
    def is_connection_healthy(self) -> bool:
        """Check if connection is healthy"""
        return self.time_since_last_heartbeat() < DEFAULT_HEARTBEAT_TIMEOUT
