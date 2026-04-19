from __future__ import annotations

"""
IBIT failure diagnostics.
"""
import time
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional


class IBITFailureDiagnostic:
    """Structured IBIT failure diagnostics"""
    
    def __init__(self) -> None:
        self.failed_phase = None
        self.phases_completed = []
        self.monitor_status = None
        self.recent_errors = deque(maxlen=20)
        self.vehicle_state = None
        self.arm_attempts = 0
        self.failure_time = None
        self.failure_reason = None
    
    def record_phase_complete(self, phase_name: str) -> None:
        """Record that a phase completed"""
        if phase_name not in self.phases_completed:
            self.phases_completed.append(phase_name)
    
    def record_error(self, severity: str, message: str) -> None:
        """Record an error message"""
        self.recent_errors.append({
            'timestamp': time.time(),
            'severity': severity,
            'message': message
        })
    
    def set_failure_info(self, phase: str, reason: str) -> None:
        """Set failure information"""
        self.failed_phase = phase
        self.failure_reason = reason
        self.failure_time = time.time()
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive failure report"""
        return {
            'failure_time': datetime.fromtimestamp(self.failure_time).strftime('%Y-%m-%d %H:%M:%S') if self.failure_time else None,
            'failed_phase': self.failed_phase,
            'failure_reason': self.failure_reason,
            'phases_completed': self.phases_completed,
            'test_progress': f"{len(self.phases_completed)}/4 phases",
            'arm_attempts': self.arm_attempts,
            'monitor_status': self.monitor_status,
            'recent_errors': list(self.recent_errors),
            'vehicle_state': self.vehicle_state,
            'recommended_action': self.get_recommendation()
        }
    
    def get_recommendation(self) -> str:
        """Get recommended action based on failure"""
        if not self.failure_reason:
            return "Unknown failure - check logs"
        
        if 'ARM' in self.failure_reason.upper():
            if self.monitor_status and len(self.monitor_status.get('set_monitors', [])) > 0:
                return "ARM failed due to SET monitors - investigate monitor conditions"
            return "ARM failed - check vehicle health and safety conditions"
        
        if 'TIMEOUT' in self.failure_reason.upper():
            if len(self.phases_completed) == 0:
                return "Test never started - check IBIT initialization"
            return f"Test stalled at {self.failed_phase} - check actuator hardware"
        
        if 'MONITOR' in self.failure_reason.upper():
            return "Monitor issues - verify override functionality and clear all monitors"
        
        return "Review diagnostics and try again"
    
    def format_display(self) -> str:
        """Format diagnostics for console display"""
        lines = []
        lines.append("=" * 60)
        lines.append("⚠⚠⚠ IBIT FAILURE DIAGNOSTICS ⚠⚠⚠")
        lines.append("=" * 60)
        
        if self.failure_time:
            lines.append(f"Failure Time: {datetime.fromtimestamp(self.failure_time).strftime('%H:%M:%S')}")
        
        lines.append(f"Failed Phase: {self.failed_phase or 'Unknown'}")
        lines.append(f"Reason: {self.failure_reason or 'Unknown'}")
        lines.append("")
        
        lines.append("Test Progress:")
        phases = ['WAIT_FOR_SETTLE', 'ELEVONS', 'RUDDERS', 'TVC']
        for phase in phases:
            status = '✓' if phase in self.phases_completed else '✗'
            lines.append(f"  {status} {phase}")
        lines.append(f"  Progress: {len(self.phases_completed)}/4 phases")
        lines.append("")
        
        if self.arm_attempts > 0:
            lines.append(f"ARM Attempts: {self.arm_attempts}")
        
        if self.monitor_status:
            set_monitors = self.monitor_status.get('set_monitors', [])
            lines.append(f"SET Monitors: {len(set_monitors)}")
            if set_monitors:
                lines.append(f"  IDs: {set_monitors}")
        
        if self.recent_errors:
            lines.append("\nRecent Errors:")
            for error in list(self.recent_errors)[-5:]:
                lines.append(f"  [{error['severity']}] {error['message']}")
        
        lines.append("\nRecommended Action:")
        lines.append(f"  {self.get_recommendation()}")
        lines.append("=" * 60)
        
        return "\n".join(lines)
