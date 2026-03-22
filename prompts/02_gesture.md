# Prompt: Gesture Interpreter (`shared/gesture.py`)

## Task
Convert raw IMU samples from the queue into a simple, game-ready `GestureState` published every sensor tick (~100Hz). The gesture thread must be lock-safe so the pygame (game) thread can read state at 60fps without stalling.

## GestureState fields
```python
@dataclass
class GestureState:
    paddle_velocity: float = 0.0   # [-1.0 … +1.0], neg=left, pos=right
    launch:          bool  = False  # True for one tick on wrist flick
    spin:            float = 0.0   # [-1.0 … +1.0], wrist twist → ball curve
    tilt_y:          float = 0.0   # [-1.0 … +1.0], forward/back (Snake up/down)
    raw_ax:          float = 0.0   # calibration-relative tilt (debug HUD)
    raw_gz:          float = 0.0   # smoothed gz (debug HUD)
    calibrated:      bool  = False # False while collecting calibration samples

    # Absolute IMU values for calibration visualizer:
    abs_ax: float = 0.0   # smoothed absolute ax (g)
    abs_ay: float = 0.0   # smoothed absolute ay (g)
    abs_az: float = 0.0   # smoothed absolute az (g)
    abs_gx: float = 0.0   # raw gyro gx (°/s)
    abs_gy: float = 0.0   # raw gyro gy (°/s)
    abs_gz: float = 0.0   # raw gyro gz (°/s)
```

## GestureConfig (tunable parameters)
```python
@dataclass
class GestureConfig:
    tilt_threshold:     float = 0.05   # dead-zone (g); ~3° of tilt
    tilt_max:           float = 0.50   # g at which paddle reaches full speed (~30°)
    flick_threshold:    float = 200.0  # °/s peak in flick_window → LAUNCH
    alpha:              float = 0.05   # IIR low-pass factor (2Hz cutoff at 100Hz)
    flick_window:       int   = 6      # samples for peak detection (60ms at 100Hz)
    twist_dead_zone:    float = 30.0   # gyro dead-zone (°/s)
    launch_cooldown:    float = 0.40   # min seconds between LAUNCH events
    calibration_samples: int  = 100   # ~1s at 100Hz
    gesture_cooldown:   float = 0.80  # accessible mode inter-gesture cooldown
```

## Processing pipeline (runs in background thread, ~100Hz)

### 1. Gravity extraction (IIR low-pass)
```python
smooth_ax = alpha * ax + (1 - alpha) * smooth_ax   # same for ay, az, gz
```
Separates DC gravity from AC motion acceleration.

### 2. Auto-calibration (first 100 samples)
- Collect `(smooth_ax, smooth_ay, smooth_az)` for 100 samples
- Average → `cal_ax, cal_ay, cal_az` (neutral gravity vector)
- Until complete: publish `calibrated=False`, `paddle_velocity=0`

### 3. Tilt → paddle_velocity
```python
tilt = smooth_ax - cal_ax   # lateral tilt relative to calibrated neutral
if abs(tilt) < tilt_threshold:
    velocity = 0.0
else:
    magnitude = (abs(tilt) - tilt_threshold) / (tilt_max - tilt_threshold)
    magnitude = clamp(magnitude, 0.0, 1.0)
    velocity = magnitude * sign(tilt)   # negative = left, positive = right
```

### 4. Forward/back tilt (ay) → tilt_y  (for Snake up/down)
Same formula as above but using `smooth_ay - cal_ay`.

### 5. Flick detection → launch
```python
gy_window.append(s.gy)   # rolling deque of last flick_window samples
if len(gy_window) == flick_window:
    peak = max(abs(v) for v in gy_window)
    if peak > flick_threshold and time_since_last_launch > launch_cooldown:
        launch = True
        last_launch_time = now
```

### 6. Twist → spin
```python
if abs(smooth_gz) < twist_dead_zone:
    spin = 0.0
else:
    spin = (smooth_gz ∓ twist_dead_zone) / 200.0   # clamp [-1, 1]
```

### 7. Queue idle decay
When the sensor queue is empty (timeout 50ms), decay `paddle_velocity *= 0.85` to prevent drift if sensor goes quiet.

## Threading
```python
class GestureInterpreter:
    def start(self) -> None   # launches daemon thread
    def stop(self) -> None    # joins thread
    def get_state(self) -> GestureState   # thread-safe snapshot (copy under lock)
    def recalibrate(self) -> None          # restart calibration mid-session
```

## KeyboardFallback
Must implement the same interface for testing without a sensor:
```python
class KeyboardFallback:
    def press_left(self) / release_left(self)
    def press_right(self) / release_right(self)
    def trigger_launch(self) -> None   # one-shot, consumed by next get_state()
    def get_state(self) -> GestureState
    def start(self) / stop(self)   # no-ops
```
KeyboardFallback sets `paddle_velocity = ±0.85` (not ±1.0 to avoid max-speed feel). `calibrated=True` always.

## Notes
- `abs_ax/ay/az/gx/gy/gz` fields are populated from the raw/smooth values for the calibration visualizer — not used by Bricks/Snake
- `GestureState` dataclass defaults to 0.0/False so `KeyboardFallback` omitting the `abs_*` fields is fine
