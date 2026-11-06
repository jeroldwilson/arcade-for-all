---
name: ble-sensor
description: >-
  Use this skill when working on MetaMotion BLE sensor connectivity,
  IMU data streaming, raw GATT protocol commands, sensor fusion mode,
  LED/haptic control, or debugging BLE connection issues. Covers
  shared/sensor.py and the MetaWear binary protocol.
---

# BLE Sensor Skill — MetaMotion IMU Interface

## Overview

`shared/sensor.py` (~955 lines) implements a **bleak-only** BLE interface to MbientLab
MetaMotion S/R/RL/C boards. No native `libmetawear` dependency — all commands are raw
GATT writes to the MetaWear binary register protocol.

## Architecture

```
MetaMotionSensor
├── start_background(address)   ← spawns daemon thread with asyncio event loop
│   ├── scan()                  ← BleakScanner, filters by METAWEAR_SERVICE_UUID
│   ├── connect(address)        ← BleakClient, writes connection params
│   └── start_streaming()       ← configures acc/gyro/SF, subscribes GATT notify
│       └── _notification_handler()  ← parses binary packets → IMUSample → data_queue
├── data_queue                  ← thread-safe queue.Queue[IMUSample], maxsize=256
├── stop_background()           ← signals shutdown event, joins thread
└── vibrate() / set_ambient_light()  ← haptic buzz / LED color control
```

## Key Data Type

```python
@dataclass
class IMUSample:
    timestamp: float          # time.monotonic()
    ax, ay, az: float         # accelerometer (g), ±4g range
    gx, gy, gz: float         # gyroscope (°/s), ±500°/s range
    hw_heading: float         # Bosch Kalman heading 0-360° (drift-free yaw)
    hw_pitch: float           # pitch -90 to +90°
    hw_roll: float            # roll -180 to +180°
    hw_fusion_valid: bool     # True once hardware fusion data is arriving
```

## MetaWear Binary Protocol

All commands are raw byte arrays written to `METAWEAR_COMMAND_CHAR_UUID`.
Responses arrive on `METAWEAR_NOTIFY_CHAR_UUID`.

### BLE UUIDs (fixed across all MbientLab hardware)

| UUID | Purpose |
|------|---------|
| `326a9000-...` | MetaWear Service |
| `326a9001-...` | Command Characteristic (write) |
| `326a9006-...` | Notify Characteristic (subscribe) |

### Module Register Map

| Module | ID | Registers |
|--------|----|-----------|
| LED | `0x02` | PLAY=0x01, STOP=0x02, CONFIG=0x03 |
| Accelerometer (BMI160) | `0x03` | POWER=0x01, ENABLE=0x02, CONFIG=0x03, DATA=0x04 |
| Haptic | `0x08` | BUZZ=0x01 |
| Settings | `0x11` | CONN_PARAMS=0x09 |
| Gyroscope (BMI160) | `0x13` | POWER=0x01, ENABLE=0x02, CONFIG=0x03, DATA=0x05 |
| Sensor Fusion | `0x19` | ENABLE=0x01, MODE=0x02, EULER=0x08, CAL_STATE=0x0B |

### Streaming Modes

**Preferred: Sensor Fusion (module 0x19)**
- Probes module with `[0x19, 0x80]`; if present, uses Bosch Kalman Filter
- IMUPlus mode (acc+gyro, no magnetometer): `[0x19, 0x02, 0x02, 0x31]`
- Streams Euler angles as 4×float32 (heading, pitch, roll, yaw)
- Also streams corrected acc (0x04) and corrected gyro (0x05) as 3×float32

**Fallback: Raw Acc + Gyro (modules 0x03 + 0x13)**
- Activated if SF module absent or no SF data after 4s timeout
- Acc: BMI160 at 100Hz, ±4g → `_ACC_SCALE = 4.0 / 32768.0`
- Gyro: BMI160 at 100Hz, ±500°/s → `_GYRO_SCALE = 500.0 / 32768.0`
- Packets: 6 bytes = 3×int16 (x, y, z)

### Start Sequence (Raw Mode)

```
1. Connection params:  [0x11, 0x09, ...]  (7.5ms interval)
2. Acc config:         [0x03, 0x03, 0x28, 0x01]  (100Hz, ±4g)
3. Acc subscribe:      [0x03, 0x04, 0x01]
4. Acc enable:         [0x03, 0x02, 0x01, 0x00]
5. Acc start:          [0x03, 0x01, 0x01]
6. Gyro config:        [0x13, 0x03, 0x28, 0x02]  (100Hz, ±500°/s)
7. Gyro subscribe:     [0x13, 0x05, 0x01]
8. Gyro enable:        [0x13, 0x02, 0x01, 0x00]
9. Gyro start:         [0x13, 0x01, 0x01]
```

## Threading Model

- **BLE thread** runs its own `asyncio.AbstractEventLoop` (daemon thread)
- `data_queue` is the **only** cross-thread communication channel
- `stop_background()` sets `_shutdown_event` from the main thread via `call_soon_threadsafe`
- Haptic writes use `response=False` to avoid CoreBluetooth error 30

## Known Gotchas

1. **Haptics**: MetaMotionR boards lack internal haptic motors. Writing with
   `response=True` to module 0x08 fails with error 30. Use `response=False`
   and auto-disable on first failure (`_haptic_disabled` flag).
2. **SF config byte**: The config nibble is `lower=acc_range, upper=gyro_range+1`.
   Using wrong packing causes BLE disconnect.
3. **Double-emit bug (fixed)**: In raw mode, `_emit_sample()` used dirty flags
   (`_acc_dirty`, `_gyro_dirty`) to emit only when both sensors have fresh data.
4. **No reconnect recovery**: If BLE disconnects during gameplay, the sensor
   thread dies. Games must handle `gesture_src` returning stale `GestureState`.
