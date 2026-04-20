# Test Flow

Step-by-step flow of what happens when an operator runs a test.

---

## 1. Launch

```
Operator double-clicks start.bat
         │
         ▼
   ┌─────────────┐
   │ Auto-install │ (first run only — installs Python deps, builds web frontend)
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │ Server start │ ws://0.0.0.0:18889  +  http://0.0.0.0:18890
   └──────┬──────┘
          ▼
   Browser opens → http://localhost:18890
```

---

## 2. Setup (operator actions in the web GUI)

```
   ┌──────────────────────────────────────────────────┐
   │                   WEB GUI                         │
   │                                                   │
   │  1. Add UUTs (serial, IP, port, relay line)       │
   │     ┌─────────┐ ┌─────────┐ ┌─────────┐          │
   │     │ RR-B1   │ │ RR-B2   │ │ RR-B3   │ ...      │
   │     │ 10.0.1.1│ │ 10.0.1.2│ │ 10.0.1.3│          │
   │     │ :13002  │ │ :13002  │ │ :13002  │          │
   │     │ relay 0 │ │ relay 1 │ │ relay 2 │          │
   │     └─────────┘ └─────────┘ └─────────┘          │
   │                                                   │
   │  2. Select mode:  [IBIT]  or  [Playback]          │
   │     (Playback: click folder icon to upload CSV)   │
   │                                                   │
   │  3. Set duration:  [9] [Hours]                    │
   │                                                   │
   │  4. Click  [ ▶ Start IBIT Test ]                  │
   └──────────────────────────────────────────────────┘
```

---

## 3. IBIT Test Flow (per UUT, repeated round-robin)

```
   START
     │
     ▼
   ┌──────────────────────┐
   │ Enable relay (load)  │  NI-DAQmx sets relay line HIGH
   └──────────┬───────────┘
              ▼
   ┌──────────────────────┐
   │ Connect UDP MAVLink  │  udpin:{ip}:13002, Pandion dialect 102
   │ Send GCS heartbeat   │  3-burst at 100ms, then 1 Hz steady
   │ Wait for vehicle HB  │  timeout: 10s
   └──────────┬───────────┘
              ▼
   ┌──────────────────────┐
   │ ARM loop             │  max 20 iterations, 60s timeout
   │  ├─ Read monitors    │  PANDION_MONITOR_CURRENT_STATUS (5 Hz)
   │  ├─ Suppress SET     │  PANDION_MONITOR_OVERRIDE_CMD (cmd=1)
   │  ├─ Send ARM cmd     │  COMMAND_LONG(400), param1=1
   │  └─ Check regime     │  PANDION_STATUS.flight_regime == 1?
   └──────────┬───────────┘
              ▼
   ┌──────────────────────┐
   │ Wait for OPERATE     │  actuation_state == 2 (OPERATE)
   │ (TAU Mk2: POS_CHECK  │  may pass through state 6 first)
   │  → OPERATE, ~2s)     │
   └──────────┬───────────┘
              ▼
   ┌──────────────────────┐
   │ Clear monitors       │  5s window — suppress any newly-set
   └──────────┬───────────┘
              ▼
   ┌──────────────────────┐
   │ Request PLAYBACK     │  ACTUATION_REQUEST_MODE(4)
   │ Wait for mode == 4   │  timeout: 10s
   └──────────┬───────────┘
              ▼
   ┌──────────────────────┐
   │ Clear monitors       │  3s window
   └──────────┬───────────┘
              ▼
   ┌──────────────────────┐
   │ Request IBIT         │  ACTUATION_REQUEST_MODE(1)
   │ Wait for mode == 1   │  timeout: 30s
   └──────────┬───────────┘
              ▼
   ┌──────────────────────────────────────────────┐
   │              IBIT IN PROGRESS                 │
   │                                               │
   │  Firmware runs these phases automatically:    │
   │                                               │
   │  BEGIN ──► SETTLE (500ms)                     │
   │              │                                │
   │              ▼                                │
   │           ELEVONS (5s)                        │
   │           Triangle wave ±3500 cdeg            │
   │              │                                │
   │              ▼                                │
   │           RUDDERS (10s)                       │
   │           Triangle wave ±6000 cdeg            │
   │              │                                │
   │              ▼                                │
   │           TVC (5s)                            │
   │           Circular sweep ±6000 cdeg           │
   │              │                                │
   │              ▼                                │
   │           COMPLETE                            │
   │                                               │
   │  Test SW monitors:                            │
   │  • actuation_ibit_substate (phase tracking)   │
   │  • actuation_ibit_mon_status (mistracking OR) │
   │  • Detects IBIT→OPERATE mode transition       │
   │    (completion signal, NOT substate==5)        │
   └──────────────────┬──────────────────────────┘
                      ▼
   ┌──────────────────────┐
   │ Evaluate result      │
   │                      │
   │ mistracking == 0x00  │──► PASS
   │ mistracking != 0x00  │──► FAIL
   │                      │
   │ Bitmask:             │
   │  0x01 Upper Rudder   │
   │  0x02 Lower Rudder   │
   │  0x04 Left TVC Up    │
   │  0x08 Left TVC Low   │
   │  0x10 Right TVC Up   │
   │  0x20 Right TVC Low  │
   │  0x40 Left Elevon    │
   │  0x80 Right Elevon   │
   └──────────┬───────────┘
              ▼
   ┌──────────────────────┐
   │ Restore vehicle      │
   │  ├─ Request OPERATE  │
   │  ├─ Clear overrides  │
   │  ├─ DISARM           │
   │  └─ Disable relay    │
   └──────────┬───────────┘
              ▼
   ┌──────────────────────┐
   │ Next UUT             │  round-robin: UUT1 → UUT2 → ... → UUT1
   │ (or batch complete   │  if duration expired or all UUTs failed 3x
   │  if time expired)    │
   └──────────────────────┘
```

---

## 4. Flight Profile Playback Flow (per UUT)

Same preparation as IBIT (ARM → OPERATE → PLAYBACK), plus:

```
   ┌──────────────────────────────────────────────┐
   │         PLAYBACK PREPARATION                  │
   │                                               │
   │  Set CLASSIC_MODE_EN = 1                      │
   │  Operator power-cycles vehicle manually       │
   │  (bench PSU or battery — software prompts)    │
   │  Re-ARM → OPERATE → PLAYBACK                 │
   └──────────────────┬──────────────────────────┘
                      ▼
   ┌──────────────────────────────────────────────┐
   │  RELAY ON ← load relay enabled               │
   │                                               │
   │  Stream PANDION_RR_PLAYBACK_COMMAND at 100 Hz │
   │  (CSV auto-resampled if recorded at != 100Hz) │
   │                                               │
   │  Per frame:                                   │
   │  ├─ Send 8 servo + 2 engine commands          │
   │  ├─ Read ACTUATION_SYS_STATUS feedback        │
   │  ├─ Compute |command - feedback| per surface  │
   │  └─ Track max delta per surface               │
   │                                               │
   │  Progress: logged every 10%                   │
   └──────────────────┬──────────────────────────┘
                      ▼
   ┌──────────────────────┐
   │ Evaluate result      │
   │                      │
   │ All deltas ≤ 500 cdeg│──► PASS
   │ Any delta > 500 cdeg │──► FAIL (lists which surfaces)
   │                      │
   │ (500 cdeg = firmware  │
   │  IBIT_TVC_SERVO_      │
   │  TRACKING_MAX_DELTA)  │
   └──────────┬───────────┘
              ▼
   Restore vehicle (same as IBIT)
              ▼
   Next UUT (round-robin)
```

---

## 5. Batch lifecycle

```
   ┌─────────────────────────────────────────────────────────┐
   │                    BATCH LOOP                            │
   │                                                          │
   │  while time_remaining > 0 and active_uuts > 0:          │
   │      uut = next UUT in round-robin                       │
   │      if uut failed 3x: skip                              │
   │      run IBIT or Playback on uut                         │
   │      if PASS: uut.iterations_completed += 1              │
   │      if FAIL: uut.consecutive_failures += 1              │
   │          if consecutive_failures >= 3:                    │
   │              mark as FAILED_PERMANENT, skip from now on   │
   │          else:                                            │
   │              auto-retry on next round                     │
   │                                                          │
   │  Operator can click [Stop] at any time                   │
   │  → current IBIT runs to completion, then batch ends      │
   │  → relay always goes OFF on exit                         │
   └─────────────────────────────────────────────────────────┘
```

---

## 6. What the operator sees in the GUI

```
   ┌────────────────────────────────────────────────────────┐
   │  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐ │
   │  │ UUT Table │  │ Vehicle  │  │ IBIT Display         │ │
   │  │          │  │ Status   │  │                      │ │
   │  │ RR-B1  1 │  │          │  │ ● BEGIN              │ │
   │  │ RR-B2  0 │  │ Link: ●  │  │ ● SETTLE             │ │
   │  │ RR-B3  0 │  │ Armed: ● │  │ ● ELEVONS  ◄── here  │ │
   │  │          │  │ Mode: ●  │  │ ○ RUDDERS            │ │
   │  │ iters ──►│  │          │  │ ○ TVC                │ │
   │  │ status──►│  │ Relay: ● │  │ ○ COMPLETE           │ │
   │  └──────────┘  └──────────┘  └──────────────────────┘ │
   │                                                        │
   │  ┌──────────────────────┐  ┌──────────────────────┐   │
   │  │ Actuator Feedback    │  │ Log Panel            │   │
   │  │                      │  │                      │   │
   │  │ L Elevon:  1234 cdeg │  │ ✓ Connected to RR-B1 │   │
   │  │ R Elevon: -1234 cdeg │  │ ARM attempt 1/20     │   │
   │  │ Up Rudder:  567 cdeg │  │ ✓ ARMED              │   │
   │  │ Dn Rudder: -567 cdeg │  │ → OPERATE            │   │
   │  │ ...                  │  │ → PLAYBACK            │   │
   │  └──────────────────────┘  │ → IBIT               │   │
   │                            │ [50%] Frame 150/300   │   │
   │  ┌──────────────────────┐  │ ✓ IBIT PASS          │   │
   │  │ Elapsed: 01:23       │  └──────────────────────┘   │
   │  │ Remaining: 07:37     │                              │
   │  └──────────────────────┘                              │
   │                                                        │
   │  [ ▶ Start ]  [ ■ Stop ]  [ ⚡ EMERGENCY STOP ]       │
   └────────────────────────────────────────────────────────┘
```

---

## 7. Timing reference (from Pandion firmware)

| Parameter | Value | Source |
|-----------|-------|--------|
| Actuation task rate | 100 Hz | `actuation.h:13` |
| IBIT settle phase | 500 ms | `actuation.c:29` |
| IBIT elevon phase | 5,000 ms | `actuation.c:30` |
| IBIT rudder phase | 10,000 ms | `actuation.c:31` |
| IBIT TVC phase | 5,000 ms | `actuation.c:32` |
| Mistracking threshold | 500 cdeg | `actuation.c:33` |
| TVC consecutive cycles | 5 (50 ms) | `actuation.c:34` |
| Elevon/rudder mistracking | Instant | `actuation.c:716-723` |
| Elevon servo limits | ±3,500 cdeg | firmware config |
| Rudder servo limits | ±6,000 cdeg | firmware config |
| TVC servo limits | ±6,000 cdeg | firmware config |
| Playback command rate | 100 Hz | matches actuation task rate |
| GCS heartbeat | 1 Hz + 3-burst on connect | MAVLink convention |
| ACTUATION_SYS_STATUS downlink | 5 Hz | telemetry config |
| PANDION_STATUS downlink | 10 Hz | telemetry config |
| MAVLink port | 13002 (UDP) | QGC channel |

