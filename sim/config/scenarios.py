# -*- coding: utf-8 -*-
"""
sim.config.scenarios -- Pre-built test scenarios.

Each scenario is a dict of PandionVehicleSim constructor kwargs.
Use these to quickly spin up vehicles with specific fault profiles.
"""

# Normal healthy vehicle -- IBIT passes
HEALTHY = {
    'ibit_pass': True,
    'boot_monitors': [0, 1, 2, 3, 4, 5],
    'post_arm_monitors': [10],
    'ibit_duration_scale': 1.0,
    'boot_time_s': 5.0,
    'packet_drop_rate': 0.0,
}

# Healthy vehicle, fast for development
HEALTHY_FAST = {
    **HEALTHY,
    'ibit_duration_scale': 0.3,
    'boot_time_s': 1.5,
}

# Elevon mistracking -- both elevons fail IBIT
ELEVON_FAIL = {
    'ibit_pass': False,
    'mistracking_flags': 0xC0,  # LEFT_ELEVON + RIGHT_ELEVON
    'boot_monitors': [0, 1, 5],
    'post_arm_monitors': [10, 11],
    'ibit_duration_scale': 0.3,
    'boot_time_s': 1.5,
}

# Single TVC fail
TVC_FAIL = {
    'ibit_pass': False,
    'mistracking_flags': 0x04,  # LEFT_TVC_UPPER only
    'boot_monitors': [0, 1, 2, 3],
    'post_arm_monitors': [10],
    'ibit_duration_scale': 0.3,
    'boot_time_s': 1.5,
}

# Rudder fail
RUDDER_FAIL = {
    'ibit_pass': False,
    'mistracking_flags': 0x03,  # UPPER + LOWER RUDDER
    'boot_monitors': [0, 1, 2, 3],
    'post_arm_monitors': [10],
    'ibit_duration_scale': 0.3,
    'boot_time_s': 1.5,
}

# All surfaces fail
TOTAL_FAIL = {
    'ibit_pass': False,
    'mistracking_flags': 0xFF,
    'boot_monitors': [0, 1, 2, 3, 4, 5],
    'post_arm_monitors': [10],
    'ibit_duration_scale': 0.3,
    'boot_time_s': 1.5,
}

# Intermittent left elevon fault
INTERMITTENT_ELEVON = {
    'ibit_pass': True,  # May pass or fail depending on random timing
    'boot_monitors': [0, 1, 2, 3],
    'post_arm_monitors': [10],
    'intermittent_servos': {'left_elevon': 2.0},  # 2 faults/second avg
    'ibit_duration_scale': 0.5,
    'boot_time_s': 1.5,
}

# GNSS degrades during IBIT
GNSS_DEGRADED = {
    'ibit_pass': True,
    'gnss_degrade_during_ibit': True,
    'boot_monitors': [0, 1, 2, 3, 4, 5],
    'post_arm_monitors': [10],
    'ibit_duration_scale': 0.5,
    'boot_time_s': 2.0,
}

# Noisy link (5% packet drop)
NOISY_LINK = {
    'ibit_pass': True,
    'packet_drop_rate': 0.05,
    'boot_monitors': [0, 1, 2, 3],
    'post_arm_monitors': [10],
    'ibit_duration_scale': 0.5,
    'boot_time_s': 2.0,
}

# Multiple IBIT cycles (vehicle runs IBIT 2 times)
MULTI_CYCLE = {
    'ibit_pass': True,
    'ibit_cycles': 2,
    'boot_monitors': [0, 1, 2, 3],
    'post_arm_monitors': [10],
    'ibit_duration_scale': 0.3,
    'boot_time_s': 1.5,
}

# Stress test: many monitors, noisy, slow boot
STRESS = {
    'ibit_pass': True,
    'boot_monitors': list(range(20)),  # 20 monitors on boot
    'post_arm_monitors': [10, 11, 12, 13, 14],
    'transient_monitor_chance': 0.3,
    'packet_drop_rate': 0.02,
    'ibit_duration_scale': 0.5,
    'boot_time_s': 3.0,
    'eval_window_s': 1.0,
}
