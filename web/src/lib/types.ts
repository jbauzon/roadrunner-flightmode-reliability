// ── WebSocket Protocol Types ─────────────────────────────────────────────────
// Shared types for the JSON messages between Python backend and React frontend.

// ---------------------------------------------------------------------------
// Domain models (mirror Python vehicle/connection.py + vehicle/constants.py)
// ---------------------------------------------------------------------------

export interface UUT {
  serial_number: string
  ip_address: string
  port: number
  relay_line: number
  status: UUTStatus
  iterations_completed: number
  consecutive_failures: number
  soft_failures: number
  last_result?: string
}

export type UUTStatus =
  | 'READY'
  | 'TESTING'
  | 'PASSED'
  | 'FAILED'
  | 'RETRY'
  | 'FAILED_PERMANENT'
  | 'SKIPPED'

export type TestMode = 'ibit' | 'playback'

export type ActuationMode = 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7

export const ACTUATION_MODE_NAMES: Record<number, string> = {
  0: 'OFF',
  1: 'IBIT',
  2: 'OPERATE',
  3: 'MANUAL',
  4: 'PLAYBACK',
  5: 'TRIM',
  6: 'POS CHECK',
  7: 'TERMINAL',
}

export type IBITPhase =
  | 'IDLE'
  | 'BEGIN'
  | 'WAIT_FOR_SETTLE'
  | 'ELEVONS'
  | 'RUDDERS'
  | 'TVC'
  | 'COMPLETE'
  | 'PASS'
  | 'FAIL'
  // Preparation phases
  | 'CONNECTING'
  | 'CAPTURING STATE'
  | 'ARMING'
  | 'CLEARING MONITORS'
  | 'PLAYBACK'
  | 'ENTERING IBIT'

export type AlertSeverity = 'info' | 'warning' | 'error' | 'critical'

export interface ActuatorFeedback {
  left_elevon_feedback_cdeg?: number
  left_elevon_current_mA?: number
  left_elevon_motor_temp_degC?: number
  right_elevon_feedback_cdeg?: number
  right_elevon_current_mA?: number
  right_elevon_motor_temp_degC?: number
  dorsal_rudder_feedback_cdeg?: number
  dorsal_rudder_current_mA?: number
  dorsal_rudder_motor_temp_degC?: number
  ventral_rudder_feedback_cdeg?: number
  ventral_rudder_current_mA?: number
  ventral_rudder_motor_temp_degC?: number
  left_tvc_upper_feedback_cdeg?: number
  left_tvc_upper_current_mA?: number
  left_tvc_upper_motor_temp_degC?: number
  left_tvc_lower_feedback_cdeg?: number
  left_tvc_lower_current_mA?: number
  left_tvc_lower_motor_temp_degC?: number
  right_tvc_upper_feedback_cdeg?: number
  right_tvc_upper_current_mA?: number
  right_tvc_upper_motor_temp_degC?: number
  right_tvc_lower_feedback_cdeg?: number
  right_tvc_lower_current_mA?: number
  right_tvc_lower_motor_temp_degC?: number
}

export interface TestStatistics {
  total_iterations: number
  total_passes: number
  total_fails: number
  pass_rate: number
  avg_duration: number
  per_uut: Record<string, {
    iterations: number
    passes: number
    fails: number
    last_result: string
  }>
}

export interface TestConfig {
  ibit_timeout: number
  phase_timeout: number
  arm_timeout: number
  max_arm_iterations: number
  skip_arm_for_ibit: boolean
}

export interface DAQStatus {
  initialized: boolean
  device: string | null
  num_lines: number
  sitl_active: boolean
  devices: string[]
}

export interface BatchStatus {
  active: boolean
  mode: TestMode
  current_uut_index: number
  current_uut_serial: string | null
  elapsed_seconds: number
  remaining_seconds: number
  total_uuts: number
  active_uuts: number
}

// ---------------------------------------------------------------------------
// Surface definitions (for actuator feedback table)
// ---------------------------------------------------------------------------

export const SURFACES = [
  { key: 'left_elevon',     display: 'L Elevon',    bit: 64  },
  { key: 'right_elevon',    display: 'R Elevon',    bit: 128 },
  { key: 'dorsal_rudder',   display: 'Dorsal Rud',  bit: 1   },
  { key: 'ventral_rudder',  display: 'Ventral Rud', bit: 2   },
  { key: 'left_tvc_upper',  display: 'L TVC Up',    bit: 4   },
  { key: 'left_tvc_lower',  display: 'L TVC Lo',    bit: 8   },
  { key: 'right_tvc_upper', display: 'R TVC Up',    bit: 16  },
  { key: 'right_tvc_lower', display: 'R TVC Lo',    bit: 32  },
] as const

export type SurfaceKey = typeof SURFACES[number]['key']

// ---------------------------------------------------------------------------
// WebSocket message types
// ---------------------------------------------------------------------------

// Server → Client (events)
export type ServerMessage =
  | { type: 'state.sync';              data: AppState }
  | { type: 'telemetry.actuator';      data: ActuatorFeedback }
  | { type: 'telemetry.vehicle_status';data: { mode: number; regime: number; armed: boolean } }
  | { type: 'telemetry.battery';       data: { voltage_mV: number; current_cA: number; soc: number } }
  | { type: 'telemetry.engine';        data: { rpm: number; egt_C: number; fuel_pump_mA: number } }
  | { type: 'ibit.state';             data: { substate: string } }
  | { type: 'ibit.mistracking';       data: { flags: number } }
  | { type: 'test.log';               data: { message: string; level: string; timestamp: string } }
  | { type: 'test.complete';          data: { success: boolean; message: string } }
  | { type: 'uut.iteration_complete'; data: { success: boolean; message: string } }
  | { type: 'test.statistics';        data: TestStatistics }
  | { type: 'test.duration';          data: { seconds: number } }
  | { type: 'test.iteration';         data: { iteration: number } }
  | { type: 'test.progress';          data: { percent: number } }
  | { type: 'test.status';            data: { status: string } }
  | { type: 'uut.update';             data: { uuts: UUT[] } }
  | { type: 'daq.status';             data: DAQStatus }
  | { type: 'daq.relay';              data: { on: boolean } }
  | { type: 'batch.status';           data: BatchStatus }
  | { type: 'connection.health';      data: { healthy: boolean } }
  | { type: 'alert';                  data: { message: string; severity: AlertSeverity } }
  | { type: 'debug.message';          data: { msg_type: string; summary: string } }
  | { type: 'error';                  data: { message: string } }

// Client → Server (commands)
export type ClientMessage =
  | { type: 'cmd.start_test';     data: { mode: TestMode; duration_seconds: number; playback_csv?: string; playback_type?: string; config?: Partial<TestConfig> } }
  | { type: 'cmd.stop_test' }
  | { type: 'cmd.emergency_stop' }
  | { type: 'cmd.add_uut';        data: { serial_number: string; ip_address: string; port: number; relay_line: number } }
  | { type: 'cmd.edit_uut';       data: { index: number; serial_number: string; ip_address: string; port: number; relay_line: number } }
  | { type: 'cmd.remove_uut';     data: { index: number } }
  | { type: 'cmd.save_uuts';      data: { path: string } }
  | { type: 'cmd.load_uuts';      data: { path: string } }
  | { type: 'cmd.detect_daq' }
  | { type: 'cmd.init_daq';       data: { device: string } }
  | { type: 'cmd.launch_sitl' }
  | { type: 'cmd.sync_state' }
  | { type: 'cmd.debug.connect';  data: { serial: string; ip: string; port: number } }
  | { type: 'cmd.debug.disconnect' }
  | { type: 'cmd.debug.mode_request'; data: { mode_id: number } }
  | { type: 'cmd.debug.arm';      data: { arm: boolean; force?: boolean } }
  | { type: 'cmd.debug.param_set'; data: { name: string; value: number } }
  | { type: 'cmd.debug.monitor_override'; data: { cmd: number; monitor_id: number } }
  | { type: 'cmd.debug.raw_command'; data: { cmd_id: number; param1: number } }

// ---------------------------------------------------------------------------
// Full application state (sent on connect via state.sync)
// ---------------------------------------------------------------------------

export interface AppState {
  uuts: UUT[]
  daq: DAQStatus
  batch: BatchStatus
  vehicle: {
    mode: number
    regime: number
    armed: boolean
    relay_on: boolean
    connection_healthy: boolean
  }
  ibit: {
    substate: string
    mistracking_flags: number
    duration_seconds: number
  }
  actuator: ActuatorFeedback
  statistics: TestStatistics | null
  test_mode: TestMode
  config: TestConfig
}

export const DEFAULT_APP_STATE: AppState = {
  uuts: [],
  daq: {
    initialized: false,
    device: null,
    num_lines: 0,
    sitl_active: false,
    devices: [],
  },
  batch: {
    active: false,
    mode: 'ibit',
    current_uut_index: -1,
    current_uut_serial: null,
    elapsed_seconds: 0,
    remaining_seconds: 0,
    total_uuts: 0,
    active_uuts: 0,
  },
  vehicle: {
    mode: 0,
    regime: 0,
    armed: false,
    relay_on: false,
    connection_healthy: false,
  },
  ibit: {
    substate: 'IDLE',
    mistracking_flags: 0,
    duration_seconds: 0,
  },
  actuator: {},
  statistics: null,
  test_mode: 'ibit',
  config: {
    ibit_timeout: 300.0,
    phase_timeout: 90.0,
    arm_timeout: 60.0,
    max_arm_iterations: 20,
    skip_arm_for_ibit: false,
  },
}
