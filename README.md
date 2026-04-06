# Multi-UUT Flight Controller Test System v4.8

Automated IBIT (Initiated Built-In Test) testing system for multiple flight controllers with DAQ relay control and comprehensive telemetry logging.

## Features

- **Multi-UUT Sequential Testing**: Test multiple flight controllers in rotation
- **DAQ Relay Control**: NI-DAQmx digital output control for power switching
- **Complete State Management**: Captures and restores vehicle state
- **IBIT Phase Tracking**: Monitors all 6 IBIT phases (BEGIN → COMPLETE)
- **Descriptive CSV Logging**: Human-readable logs with complete test lifecycle
- **Real-time Monitoring**: Live status, armed state, mode, and actuator feedback
- **Batch Testing**: Run continuous tests for days/weeks with automatic rotation

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt