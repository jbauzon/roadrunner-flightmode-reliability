# -*- coding: utf-8 -*-
"""
sim.telemetry -- MAVLink telemetry transmission.

All outbound message encoding and sending is centralized here.
The vehicle.py orchestrator calls these methods at the appropriate rates.
Each method is self-contained and handles its own exceptions.
"""
import random
import time


from .config.defaults import MAV_TYPE_VTOL_DUOROTOR


class TelemetryManager:
    """Manages all MAVLink telemetry TX for a vehicle sim."""

    def __init__(self, conn, sysid):
        self._conn = conn
        self._sysid = sysid
        self._mavutil = None
        # Import mavutil for constants
        from pymavlink import mavutil
        self._mavutil = mavutil

    def heartbeat(self):
        try:
            self._conn.mav.heartbeat_send(
                MAV_TYPE_VTOL_DUOROTOR,
                self._mavutil.mavlink.MAV_AUTOPILOT_GENERIC,
                0, 0, self._mavutil.mavlink.MAV_STATE_ACTIVE)
        except Exception:
            pass

    def pandion_status(self, flight_regime, sensors, eng1_mode, eng2_mode):
        try:
            self._conn.mav.pandion_status_send(
                status=0, flight_regime=flight_regime,
                engine1_state=eng1_mode, engine2_state=eng2_mode,
                ins_status=sensors.ins_status, ins_mode=sensors.ins_status,
                gnss_fix=list(sensors.gnss_fix),
                num_satellites=list(sensors.gnss_sats),
                gnss_compass=1, mission_operation_mode=0,
                asset_id=self._sysid)
        except Exception:
            pass

    def actuation_sys_status(self, act_state, ibit_sub, ibit_mon, servos):
        try:
            self._conn.mav.pandion_rr_actuation_sys_status_send(
                actuation_state=act_state,
                actuation_ibit_substate=ibit_sub,
                actuation_ibit_mon_status=ibit_mon,
                left_elevon_feedback_cdeg=int(servos['left_elevon'].fb),
                right_elevon_feedback_cdeg=int(servos['right_elevon'].fb),
                dorsal_rudder_feedback_cdeg=int(servos['dorsal_rudder'].fb),
                ventral_rudder_feedback_cdeg=int(servos['ventral_rudder'].fb),
                left_tvc_upper_feedback_cdeg=int(servos['left_tvc_upper'].fb),
                left_tvc_lower_feedback_cdeg=int(servos['left_tvc_lower'].fb),
                right_tvc_upper_feedback_cdeg=int(servos['right_tvc_upper'].fb),
                right_tvc_lower_feedback_cdeg=int(servos['right_tvc_lower'].fb),
                left_elevon_current_mA=int(servos['left_elevon'].cur),
                right_elevon_current_mA=int(servos['right_elevon'].cur),
                dorsal_rudder_current_mA=int(servos['dorsal_rudder'].cur),
                ventral_rudder_current_mA=int(servos['ventral_rudder'].cur),
                left_tvc_upper_current_mA=int(servos['left_tvc_upper'].cur),
                left_tvc_lower_current_mA=int(servos['left_tvc_lower'].cur),
                right_tvc_upper_current_mA=int(servos['right_tvc_upper'].cur),
                right_tvc_lower_current_mA=int(servos['right_tvc_lower'].cur),
                left_elevon_motor_temp_degC=int(servos['left_elevon'].temp),
                right_elevon_motor_temp_degC=int(servos['right_elevon'].temp))
        except Exception:
            pass

    def monitor_current_status(self, set_ids, setting_ids, overridden_ids):
        cs = bytearray(64)
        cg = bytearray(64)
        co = bytearray(64)
        for m in set_ids:
            if 0 <= m < 512:
                cs[m // 8] |= 1 << (m % 8)
        for m in setting_ids:
            if 0 <= m < 512:
                cg[m // 8] |= 1 << (m % 8)
        for m in overridden_ids:
            if 0 <= m < 512:
                co[m // 8] |= 1 << (m % 8)
        try:
            self._conn.mav.pandion_monitor_current_status_send(
                currently_set=bytes(cs),
                currently_setting=bytes(cg),
                currently_overridden=bytes(co))
        except Exception:
            pass

    def engine_status(self, sensors, powered):
        # Engines off: zero RPM, zero fuel pump, ambient temps
        eng_running_1 = sensors.eng1_rpm > 0
        eng_running_2 = sensors.eng2_rpm > 0
        try:
            self._conn.mav.pandion_rr_engine_status_send(
                eng_1_fuel_pump_curr_mA=int(sensors.fuel_pump_current_mA) if eng_running_1 else 0,
                eng_1_fuel_pump_speed_rpm=int(sensors.eng1_rpm * 0.8),
                eng_1_fuel_consumption_l=float(getattr(sensors, 'fuel_consumed_l', 0.0)),
                eng_1_intake_temp_degC=int(random.gauss(35, 2)) if eng_running_1 else int(random.gauss(25, 1)),
                eng_1_egt_temp_degC=int(sensors.eng1_egt),
                eng_1_speed_vs_nominal_pct=100 if eng_running_1 else 0,
                eng_1_speed=int(sensors.eng1_rpm),
                eng_1_required_speed=int(sensors.eng1_rpm) if eng_running_1 else 0,
                eng_1_mode=sensors.eng1_mode,
                eng_1_EED=0,
                eng_1_relay_state=1 if powered else 0,
                eng_2_fuel_pump_curr_mA=int(sensors.fuel_pump_current_mA) if eng_running_2 else 0,
                eng_2_fuel_pump_speed_rpm=int(sensors.eng2_rpm * 0.8),
                eng_2_fuel_consumption_l=float(getattr(sensors, 'fuel_consumed_l', 0.0)),
                eng_2_intake_temp_degC=int(random.gauss(35, 2)) if eng_running_2 else int(random.gauss(25, 1)),
                eng_2_egt_temp_degC=int(sensors.eng2_egt),
                eng_2_speed_vs_nominal_pct=100 if eng_running_2 else 0,
                eng_2_speed=int(sensors.eng2_rpm),
                eng_2_required_speed=int(sensors.eng2_rpm) if eng_running_2 else 0,
                eng_2_mode=sensors.eng2_mode,
                eng_2_EED=0,
                eng_2_relay_state=1 if powered else 0,
                hung_start_eshutdown=0)
        except Exception:
            pass

    def bms_data(self, bms):
        cell_voltages = bms.get_cell_voltage()
        try:
            self._conn.mav.pandion_rr_bms_data_send(
                which_bms=0,
                pack_voltage_mV=bms.pack_voltage,
                pack_current_cA=bms.current_cA,
                cell1_voltage_mV=cell_voltages[0],
                cell2_voltage_mV=cell_voltages[1],
                cell3_voltage_mV=cell_voltages[2],
                cell4_voltage_mV=cell_voltages[3],
                cell5_voltage_mV=cell_voltages[4],
                cell6_voltage_mV=cell_voltages[5],
                cell7_voltage_mV=cell_voltages[6],
                cell_temp1_centiC=bms.cell_temps[0],
                cell_temp2_centiC=bms.cell_temps[1],
                cell_temp3_centiC=bms.cell_temps[2],
                cell_temp4_centiC=bms.cell_temps[3],
                balancer_temp_centiC=260,
                load_switch_temp_centiC=280,
                remaining_capacity_mAh=int(bms.remaining),
                state_of_charge_percent=int(bms.soc),
                state=bms.state, balancing=0,
                min_pack_output_voltage_mV=bms.pack_voltage - 200,
                max_pack_output_voltage_mV=bms.pack_voltage + 200,
                min_discharge_current_cA=0,
                max_discharge_current_cA=500)
        except Exception:
            pass

    def wca_monitor_status(self, set_ids, event_id, event_ts, event_flags):
        wcas = [0, 0]
        for mid in set_ids:
            if mid < 64:
                wcas[0] |= (1 << mid)
            elif mid < 128:
                wcas[1] |= (1 << (mid - 64))
        try:
            self._conn.mav.pandion_wca_monitor_status_send(
                active_wcas=wcas,
                wca_event_timestamp=event_ts,
                wca_event_id=event_id,
                wca_event_flags=event_flags,
                monitor_event_timestamp=event_ts,
                monitor_event_id=event_id,
                monitor_event_flags=event_flags)
        except Exception:
            pass

    def pdu_telemetry(self, bms):
        try:
            self._conn.mav.pandion_rr_pdu_telemetry_power_send(
                pdu_battery_voltage=float(bms.pack_voltage / 1000.0),
                pdu_fuel_pressure=float(random.gauss(3.2, 0.1)),
                pdu_left_engine_current=float(random.gauss(2.5, 0.3)),
                pdu_left_engine_hssw_voltage=float(random.gauss(12.0, 0.2)),
                pdu_left_engine_pwr_rail_voltage=float(random.gauss(12.0, 0.2)),
                pdu_rigth_engine_current=float(random.gauss(2.5, 0.3)),
                pdu_right_engine_hssw_voltage=float(random.gauss(12.0, 0.2)),
                pdu_right_engine_pwr_rail_voltage=float(random.gauss(12.0, 0.2)))
        except Exception:
            pass

    def hw_selector(self, config, detections):
        try:
            self._conn.mav.pandion_rr_hardware_selector_status_send(
                configuration=config, detections=detections,
                subsystems_enabled=0xFF, config_is_by_param=0)
        except Exception:
            pass

    def command_ack(self, command, result):
        try:
            self._conn.mav.command_ack_send(
                command=command, result=result, progress=0,
                result_param2=0, target_system=255, target_component=190)
        except Exception:
            pass

    def param_value(self, name, value):
        pid = name.encode('utf-8')[:16].ljust(16, b'\x00')
        try:
            self._conn.mav.param_value_send(
                param_id=pid, param_value=value,
                param_type=9, param_count=10, param_index=0)
        except Exception:
            pass

    def statustext(self, text, severity=6):
        try:
            self._conn.mav.statustext_send(
                severity=severity,
                text=text.encode('utf-8')[:128].ljust(128, b'\x00'),
                id=0, chunk_seq=0)
        except Exception:
            pass
