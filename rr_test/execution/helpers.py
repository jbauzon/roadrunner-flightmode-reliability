from __future__ import annotations

"""
Helper utilities for test execution.
"""
from typing import Any, Dict


def _build_actuator_feedback_dict(msg: Any) -> Dict[str, float]:
    """Build actuator feedback dict from a PANDION_RR_ACTUATION_SYS_STATUS message."""
    return {
        'left_elevon_feedback_cdeg': msg.left_elevon_feedback_cdeg,
        'right_elevon_feedback_cdeg': msg.right_elevon_feedback_cdeg,
        'dorsal_rudder_feedback_cdeg': msg.dorsal_rudder_feedback_cdeg,
        'ventral_rudder_feedback_cdeg': msg.ventral_rudder_feedback_cdeg,
        'left_tvc_upper_feedback_cdeg': msg.left_tvc_upper_feedback_cdeg,
        'left_tvc_lower_feedback_cdeg': msg.left_tvc_lower_feedback_cdeg,
        'right_tvc_upper_feedback_cdeg': msg.right_tvc_upper_feedback_cdeg,
        'right_tvc_lower_feedback_cdeg': msg.right_tvc_lower_feedback_cdeg,
        'left_elevon_current_mA': msg.left_elevon_current_mA,
        'right_elevon_current_mA': msg.right_elevon_current_mA,
        'dorsal_rudder_current_mA': msg.dorsal_rudder_current_mA,
        'ventral_rudder_current_mA': msg.ventral_rudder_current_mA,
        'left_tvc_upper_current_mA': msg.left_tvc_upper_current_mA,
        'left_tvc_lower_current_mA': msg.left_tvc_lower_current_mA,
        'right_tvc_upper_current_mA': msg.right_tvc_upper_current_mA,
        'right_tvc_lower_current_mA': msg.right_tvc_lower_current_mA,
        'left_elevon_motor_temp_degC': msg.left_elevon_motor_temp_degC,
        'right_elevon_motor_temp_degC': msg.right_elevon_motor_temp_degC,
    }
