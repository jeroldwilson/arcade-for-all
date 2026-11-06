---
name: gesture-pipeline
description: >-
  Use this skill when working on gesture detection, interpretation, sensor
  fusion, tilt/flick/spin extraction, GestureState fields, GestureConfig
  tuning, SliceDetector, Madgwick AHRS, or the gesture processing thread.
  Covers shared/gesture.py, shared/gesture_detector.py, and
  shared/fusion_processor.py.
---

# Gesture Pipeline Skill

## Overview

The gesture pipeline transforms raw IMU samples from the BLE sensor into
game-consumable `GestureState` objects. It runs in a dedicated **gesture thread**
that drains the sensor's `data_queue`.

```
IMUSample (sensor.py)
    │ queue.Queue
    ▼
GestureInterpreter (gesture.py)     ← gesture thread
    ├── Low-pass gravity filter     ← α = 0.05 (2 Hz cutoff at 100 Hz)
    ├── Auto-calibration            ← 100 samples (~1s) at rest
    ├── Adaptive baseline           ← drifts when gyro < 45°/s
    ├── Tilt extraction             ← lateral/forward gravity shift
    ├── Flick detection             ← peak gyro in 6-frame window > threshold
    ├── Spin extraction             ← gz dead-zone + mapping
    ├── FusionProcessor             ← Madgwick 6-DOF AHRS (quaternion → Euler)
    └── SliceDetector               ← rapid wrist motion → SliceEvent
    │
    ▼
GestureState (35+ fields)
    │ get_state() → copied snapshot
    ▼
Game.run() loop (main thread)
```

## Key Data Types

### GestureConfig (dataclass)

Tuning knobs for the interpreter. Pre-defined configs:

| Config | tilt_threshold | flick_threshold | twist_dead | launch_cooldown | Notes |
|--------|---------------|-----------------|------------|-----------------|-------|
| `CONFIG_STANDARD` | 0.05g | 200°/s | 30°/s | 0.4s | Normal gameplay |
| `CONFIG_ACCESSIBLE` | 0.04g | 120°/s | 999°/s | 1.0s | ASTRA: spin disabled |
| `CONFIG_ACCESSIBLE_FLICK_STEER` | (same + flick_steer_enabled) | | | | Snake variant |

Notable fields:
- `alpha` (0.05): Low-pass filter coefficient. Lower = more smoothing
- `calibration_samples` (100): ~1s at 100Hz for neutral position
- `gyro_adapt_threshold` (45°/s): Below this, baseline slowly adapts
- `adapt_rate` (0.002): Baseline drift rate per sample
- `flick_steer_*`: Discrete flick-to-direction for Snake accessible mode

### GestureState (dataclass — 35+ fields)

| Category | Fields | Description |
|----------|--------|-------------|
| **Paddle** | `paddle_velocity` [-1..1] | Tilt-mapped lateral movement |
| **Launch** | `launch` (bool) | True for 1 frame on upward flick |
| **Spin** | `spin` [-1..1] | Wrist rotation → ball curve |
| **Tilt Y** | `tilt_y` [-1..1] | Forward/back tilt (Snake up/down) |
| **Raw** | `raw_ax`, `raw_gz` | Debug values |
| **Abs IMU** | `abs_ax/ay/az`, `abs_gx/gy/gz` | Smoothed absolute readings |
| **Fusion** | `qw/qx/qy/qz`, `euler_roll/pitch/yaw` | Madgwick AHRS output |
| **Angular** | `av_magnitude` | Total rotation rate (°/s) |
| **Slice** | `slice_active`, `slice_direction`, `combo_count` | SliceDetector output |
| **Steer** | `steer_left/right/up/down` | Flick-to-steer booleans |
| **Calibration** | `calibrated` (bool) | False during startup collection |

## GestureInterpreter

### Calibration Flow

1. Collects `calibration_samples` (100) frames while sensor is at rest
2. Computes mean gravity vector as neutral baseline
3. Sets `calibrated = True`
4. Adaptive baseline: when `gyro_magnitude < gyro_adapt_threshold`, slowly
   drags baseline toward current gravity (handles slow postural drift/tremors)

### Tilt Extraction

```
relative_tilt = (current_gravity - calibrated_baseline) · lateral_axis
normalized = clamp(relative_tilt / tilt_max, -1, 1)
paddle_velocity = normalized  (if |relative_tilt| > tilt_threshold, else 0)
```

### Flick Detection

- Rolling window of `flick_window` (6) gyro samples
- Peak `gy` > `flick_threshold` (200°/s standard, 120°/s accessible)
- Cooldown `launch_cooldown` (0.4s standard, 1.0s accessible)
- Produces `launch = True` for exactly one frame

### Spin / Twist

- `gz` mapped through `twist_dead_zone` (30°/s) to `spin` [-1..1]
- Disabled in accessible mode (`twist_dead_zone = 999`)

## SliceDetector (gesture_detector.py)

Detects rapid wrist slicing motions for Fruit Ninja:

```python
SliceDetector
├── 8-frame rolling window of (gx, gy, gz, av_mag, timestamp)
├── Fires SliceEvent when peak av_mag >= AV_THRESHOLD (150°/s)
├── Cooldown: SLICE_COOLDOWN = 0.25s between slices
└── Combo: timestamps within COMBO_WINDOW_SECS = 1.5s
```

### Direction Classification

From mean gyro over window:
- `|gz| > |gy|` → left/right (sign of gz)
- `|gy| > |gz|` → up/down (sign of gy)
- Diagonal variants when both are significant

### SliceEvent

```python
@dataclass
class SliceEvent:
    direction: str       # "left"|"right"|"up"|"down"|"diagonal_*"
    speed_norm: float    # 0..1 (peak / threshold×3)
    av_magnitude: float  # raw peak °/s
    timestamp: float
```

## FusionProcessor (fusion_processor.py)

Madgwick 6-DOF AHRS — combines acc + gyro into stable orientation:

```python
MadgwickFilter(beta=0.033)
├── update(ax, ay, az, gx_rads, gy_rads, gz_rads, dt)
│   ├── Normalize accel (skip if free-fall)
│   ├── Gradient descent: align measured gravity with [0,0,1]
│   ├── Integrate gyro quaternion
│   └── Normalize quaternion
└── get_state() → FusionState
    ├── qw, qx, qy, qz      (quaternion)
    ├── euler_roll/pitch/yaw  (degrees)
    ├── lin_ax/ay/az          (gravity-removed linear acceleration)
    └── av_magnitude          (total angular velocity °/s)
```

**Note**: Roll and pitch are gravity-stable. Yaw **drifts** without magnetometer.

## How Games Consume Gestures

```python
# In game.run(gesture_src):
gs = gesture_src.get_state()   # Returns a COPY of current GestureState

# Bricks: paddle movement
paddle_x += gs.paddle_velocity * PADDLE_SPEED * dt
if gs.launch: launch_ball()

# Fruit Ninja: gyro cursor
cursor_x += gs.abs_gz * GYRO_SCALE_X
cursor_y -= gs.abs_gy * GYRO_SCALE_Y

# Snake: discrete tilt or flick-to-steer
if gs.steer_left: direction = LEFT
```

## Configuration Switching

Games can swap configs at runtime:
```python
if hasattr(gesture_src, "config"):
    gesture_src.config = CONFIG_ACCESSIBLE_FLICK_STEER  # for Snake
```
`main.py` resets to base config when returning to home screen.
