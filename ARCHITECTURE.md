# RoadRunner Flight Mode IBIT Test System Architecture

## Overview

This system provides automated IBIT (Initiated Built-In Test) testing for multiple flight controllers (Units Under Test - UUTs) with DAQ relay control and comprehensive telemetry logging.

## System Components

### 1. Main Application (`main.py`)
- Entry point for PyQt5 GUI application
- Initializes main window and event loop

### 2. User Interface (`ui/`)

#### `main_window.py`
- Primary GUI orchestration
- Manages batch testing across multiple UUTs
- DAQ initialization and health monitoring
- Test configuration and UUT management
- Coordinates test execution

#### `widgets.py`
- Reusable UI components:
  - DAQSetupWidget: DAQ device selection and initialization
  - TestConfigWidget: Test parameters (duration, timeouts)
  - UUTTableWidget: UUT configuration table
  - StatusPanelWidget: Real-time connection/mode/armed status
  - IBITDisplayWidget: IBIT phase progress
  - ActuatorFeedbackWidget: Live actuator positions/currents
  - ControlButtonsWidget: Start/Stop/Emergency controls
  - LogWidget: Console-style log output

### 3. Vehicle Communication (`vehicle/`)

#### `connection.py`
- UUT class: Defines a Unit Under Test
- UUTState class: Captures complete vehicle state
- `connect_to_vehicle()`: Establishes MAVLink UDP connection
- State comparison and diff generation

#### `preparation.py`
- UUTPreparation class: Manages vehicle state lifecycle
- State capture: Saves initial vehicle configuration
- Pre-flight preparation: ARM → OPERATE → PLAYBACK → IBIT sequence
- Post-flight restoration: Returns vehicle to original state
- Monitor management: Clears safety monitors for testing

#### `constants.py`
- Centralized enums for modes, states, results
- Helper functions for name lookups
- Default values and timeouts

#### `dialects/`
- Custom MAVLink dialect for RoadRunner vehicle

### 4. Test Execution (`test/`)

#### `executor.py`
- UUTTestExecutor: Runs complete IBIT test in separate thread
- IBITPhaseTracker: Tracks progress through IBIT phases
- TestStatistics: Real-time metrics (telemetry rate, heartbeat health)
- Background workers:
  - Heartbeat sender (1 Hz GCS heartbeat)
  - Telemetry receiver (logs all messages)
  - Statistics updater
  - Connection health monitor
- Thread-safe MAVLink operations

#### `logger.py`
- TelemetryLogger: Human-readable CSV logging
- Daily log rotation
- Descriptive event logging:
  - Test control events (ARM, relay changes, IBIT requests)
  - Vehicle telemetry (actuator feedback, status)
  - Phase transitions and errors
- IBIT-focused logging mode

### 5. Hardware Control (`hardware/`)

#### `daq.py`
- SimpleDAQController: NI-DAQmx digital output control
- Auto-detection of available lines
- Thread-safe relay control
- Safety features: All relays LOW on close/error

## Data Flow

### Test Sequence for One UUT

```
1. START
   ↓
2. CONNECT (relay OFF)
   - MAVLink UDP connection
   - Start GCS heartbeat (1 Hz)
   ↓
3. STATE CAPTURE
   - Query USE_NEST parameter
   - Query armed state
   - Query actuation mode
   - Query safety monitors
   ↓
4. PRE-FLIGHT PREPARATION
   - Disable USE_NEST (if needed)
   - ARM vehicle (clear monitors if needed)
   - Wait for OPERATE mode
   - Clear monitors continuously
   - Request PLAYBACK mode
   - Clear monitors in PLAYBACK
   - Request IBIT mode
   ↓
5. ENABLE RELAY (apply load)
   ↓
6. EXECUTE IBIT TEST
   - Monitor IBIT substates:
     BEGIN → WAIT_FOR_SETTLE → ELEVONS → RUDDERS → TVC → COMPLETE
   - Log all telemetry
   - Detect completion: IBIT(1) → OPERATE(2)
   - Vehicle may run multiple IBIT cycles
   ↓
7. DISABLE RELAY (remove load)
   ↓
8. POST-FLIGHT RESTORATION
   - Ensure OPERATE mode
   - Clear overridden monitors (before disarm)
   - DISARM (if originally disarmed)
   - Request OFF mode
   ↓
9. STATE VERIFICATION
   - Capture final state
   - Compare with initial state
   - Report differences
   ↓
10. CLEANUP
    - Stop heartbeat sender
    - Close telemetry logger
    - Close MAVLink connection
    ↓
11. NEXT UUT (or COMPLETE)
```

### Batch Testing Flow

```
User clicks Start
    ↓
For each UUT in rotation:
    ↓
    Test UUT (sequence above)
    ↓
    If success: Increment iteration count
    If failure: Retry up to 3 times
    If 3 failures: Skip UUT for rest of batch
    ↓
    Check batch time remaining
    ↓
Repeat until batch time expired
    ↓
Batch complete: Generate report
```

## Threading Model

### Main Thread (Qt Event Loop)
- UI updates
- User interactions
- Timer callbacks

### Test Executor Thread (QThread)
- Runs complete test sequence
- Emits Qt signals for UI updates
- Spawns background workers

### Background Workers (daemon threads)
- **Heartbeat sender**: Sends GCS heartbeat at 1 Hz
- **Telemetry receiver**: Processes incoming MAVLink messages
- **Statistics updater**: Updates metrics every second
- **Connection health monitor**: Checks heartbeat reception
- **Log size monitor**: Tracks log file size
- **Test duration monitor**: Updates elapsed time

### Thread Safety
- All MAVLink operations protected by `master_lock`
- Qt signals used for cross-thread communication
- Atomic `running` flag for worker shutdown

## Configuration

### `config.yaml`
- Test parameters (timeouts, iteration limits)
- Hardware settings (DAQ device, relay lines)
- Logging configuration (directory, file size)
- Safety features (emergency stop, watchdog)
- UI settings (window size, update intervals)

### `app_settings.json` (runtime)
- Persisted UI state
- Last used log directory
- Window geometry
- UUT configurations

## Logging

### CSV Format
- Daily rotation (one file per day per UUT)
- Columns include:
  - Date/Time/Timestamp
  - Event Category (TEST_CONTROL, VEHICLE_DATA, SYSTEM_STATUS)
  - Event Type (ARM_REQUEST, ACTUATOR_FEEDBACK, etc.)
  - Descriptive event text
  - Current relay status, IBIT phase, armed state
  - Actuator positions (degrees), currents (mA), temperatures (°C)
  - Monitor counts

### Console Log
- Real-time updates in GUI log widget
- Color-coded (success ✓, warning ⚠, error ✗)
- Progress indicators and status messages

## Safety Features

1. **Relay Control**
   - All relays LOW on startup
   - All relays LOW on shutdown/error
   - Emergency stop button instantly disables all relays
   - Relay disabled on test failure

2. **Connection Monitoring**
   - Heartbeat timeout detection (3 seconds)
   - Automatic DAQ reconnection attempt
   - Test stops if DAQ connection lost

3. **State Management**
   - Vehicle returned to original state after each test
   - Monitors cleared before/after testing
   - Verification of state restoration

4. **Failure Handling**
   - Up to 3 retries per UUT
   - Permanently failed UUTs skipped
   - Graceful degradation

5. **System Sleep Prevention**
   - Windows: SetThreadExecutionState
   - Prevents system sleep during long tests

## Key Design Decisions

### Why PLAYBACK mode before IBIT?
Vehicle firmware requires: OPERATE → PLAYBACK → IBIT
Direct OPERATE → IBIT transition is not permitted.

### Why disable relay AFTER IBIT completes?
- IBIT tests actuators under load
- Restoration happens with relay OFF (safer)
- State verification skipped when relay OFF (can't query powered-off vehicle)

### Why continuous monitor clearing?
- Monitors can set asynchronously
- Clearing once may not be sufficient
- Continuous clearing for 5s ensures all are cleared

### Why detect IBIT completion by mode transition?
- Vehicle may run multiple IBIT cycles
- Substate 5 (COMPLETE) may appear multiple times
- Only mode transition IBIT → OPERATE confirms true completion

### Why send heartbeats?
- Vehicle expects GCS presence
- Without heartbeats, vehicle may timeout/fail commands
- 1 Hz rate is MAVLink standard

## Dependencies

- **pymavlink**: MAVLink communication protocol
- **PyQt5**: GUI framework
- **nidaqmx**: NI-DAQ hardware control (optional)
- **Python 3.7+**: Core language

## File Structure

```
RoadRunner Flight Mode IBIT/
├── main.py                  # Application entry point
├── config.yaml              # Configuration file
├── app_settings.json        # Runtime settings (created on first run)
├── requirements.txt         # Python dependencies
├── README.md               # User documentation
├── ARCHITECTURE.md         # This file
│
├── vehicle/                # Vehicle communication
│   ├── __init__.py
│   ├── connection.py       # MAVLink connection and UUT classes
│   ├── preparation.py      # State management
│   ├── constants.py        # Enums and constants
│   └── dialects/          # MAVLink dialect
│       └── pandion_vehicle_roadrunner.xml
│
├── test/                   # Test execution
│   ├── __init__.py
│   ├── executor.py         # Test orchestration
│   └── logger.py          # CSV logging
│
├── hardware/              # Hardware control
│   ├── __init__.py
│   └── daq.py            # DAQ relay control
│
├── ui/                    # User interface
│   ├── __init__.py
│   ├── main_window.py    # Main application window
│   └── widgets.py        # UI components
│
├── logs/                  # Test logs (generated)
│   └── UUT_*_day*_IBIT_Test.csv
│
└── reports/              # Test reports (generated)
    └── batch_report_*.txt
```

## Future Enhancements

1. **Database backend**: Store test results in SQLite/PostgreSQL
2. **Real-time plotting**: Graph actuator positions during IBIT
3. **Email notifications**: Alert on test failures
4. **Remote monitoring**: Web dashboard for test progress
5. **Test scheduling**: Cron-like scheduled test runs
6. **Parallel testing**: Test multiple UUTs simultaneously (requires multiple DAQ devices)
7. **Video recording**: Capture video during tests for failure analysis
8. **Automated failure diagnosis**: ML-based failure pattern recognition
