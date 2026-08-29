# 🎮 How Gesture Detection Works — A Beginner's Guide

> This explains how the **Bricks / Arcade for All** project turns wrist movements
> on a **MbientLab MetaMotion S** into game controls — no ML background required.

---

## 🌍 The Big Picture

Think of the system as a **4-stage pipeline** — like an assembly line where raw
sensor signals get processed one step at a time until they become game controls.

```
 ┌────────────────┐   ┌──────────────────┐   ┌──────────────────┐   ┌───────────┐
 │  MetaMotion S  │──▶│  Sensor Layer    │──▶│  Gesture Layer   │──▶│   Game    │
 │  (wrist band)  │   │  (sensor.py)     │   │  (gesture.py)    │   │  Logic    │
 └────────────────┘   └──────────────────┘   └──────────────────┘   └───────────┘
```

---

## 📡 Stage 1 — What Data Does the Sensor Capture?

The MetaMotion S has two physical chips inside it:

### Accelerometer (BMI160)
Measures how hard the sensor is being *pushed* in each direction. Think of it
like a tiny ball on a surface inside the chip — gravity pulls it in one direction,
and motion pushes it in another.

| Value | Meaning | Range |
|-------|---------|-------|
| `ax` | Left/Right acceleration | ±4 g |
| `ay` | Forward/Back acceleration | ±4 g |
| `az` | Up/Down acceleration | ±4 g |

> **1 g** = the force of normal gravity. If you hold the sensor flat,
> `az ≈ 1.0 g` because gravity is pulling down on it.

### Gyroscope (BMI160)
Measures how fast the sensor is *spinning* on each axis. Imagine three propellers
on the sensor — each measures spin speed in degrees per second.

| Value | Meaning | Range |
|-------|---------|-------|
| `gx` | Roll spin (like rolling a log) | ±500 °/s |
| `gy` | Pitch spin (like nodding) | ±500 °/s |
| `gz` | Yaw spin (like shaking your head "no") | ±500 °/s |

### Sample Rate
Both sensors run at **100 Hz** — 100 measurements per second. That means the
game gets a new data point every **10 milliseconds**.

### How it Arrives
The sensor communicates via **Bluetooth Low Energy (BLE)**. The sensor firmware
sends tiny binary packets over BLE, and the code in [sensor.py](file:///Users/jerold/dev/Bricks/shared/sensor.py)
decodes them into Python `IMUSample` objects.

```python
# Every 10ms, you get one of these:
@dataclass
class IMUSample:
    ax, ay, az: float    # accelerometer (g)
    gx, gy, gz: float    # gyroscope (°/s)
    hw_heading: float    # compass direction 0-360° (when fusion is active)
    hw_pitch: float      # pitch angle (hardware fusion)
    hw_roll: float       # roll angle (hardware fusion)
    hw_fusion_valid: bool
```

### Hardware Fusion (Bosch Kalman Filter)
The MetaMotion S has a **hardware sensor fusion chip** (module 0x19 in firmware).
When available, it combines acc + gyro + magnetometer using a **Kalman filter**
to produce drift-free orientation angles. This is used as the *preferred* data
source. When unavailable, the code falls back to software fusion (Madgwick).

---

## 🧮 Stage 2 — Turning Raw Numbers into Orientation (Fusion)

Raw accelerometer + gyroscope numbers alone tell you very little. You need to
**combine them** to know which way the wrist is pointing. This is called
**sensor fusion**.

### Why Do You Need Fusion?

| Sensor alone | Problem |
|---|---|
| Accelerometer only | Can't tell spin/tilt apart from sudden movement |
| Gyroscope only | Drift — small errors accumulate over time into big errors |
| Combined | Stable orientation: gyro tracks fast rotation, accel corrects drift |

### Software Fallback: Madgwick Filter ([fusion_processor.py](file:///Users/jerold/dev/Bricks/shared/fusion_processor.py))

When the hardware Kalman filter is not available, the code uses the **Madgwick
filter**, a popular open-source algorithm for wearables.

**Analogy:** Imagine you're lost in a building. The gyroscope is like counting
your steps and turns — useful but you drift off course. The accelerometer is
like gravity — it always tells you which way is "down", helping you correct your
position. The Madgwick filter blends these two sources continuously.

**Output: Quaternion → Euler Angles**

The filter outputs orientation as a **quaternion** (4 numbers: w, x, y, z).
This is mathematically stable, but hard to understand, so it's converted to
familiar angles:

| Angle | Meaning | Stability |
|---|---|---|
| Roll | Tilt left/right | ✅ Stable (gravity reference) |
| Pitch | Tilt forward/back | ✅ Stable (gravity reference) |
| Yaw | Rotation like compass | ⚠️ Drifts without magnetometer |

> **Beta parameter (0.033):** This controls how aggressively the accel corrects
> the gyro. Too high → jittery. Too low → drifts. 0.033 is the sweet spot at 100 Hz.

---

## 🎯 Stage 3 — Rule-Based Gesture Detection ([gesture.py](file:///Users/jerold/dev/Bricks/shared/gesture.py))

This is the main gesture interpreter. It runs in its own **background thread**,
processing sensor samples continuously and maintaining a `GestureState` that
games can read at any time.

### Step 1 — Auto-Calibration (The Baseline)

When you first put on the sensor, the code collects **100 samples (~1 second)**
while the wrist is at rest. It takes the **median** (not mean — more robust to
tremors) of these to define "neutral" — what `ax=0` means *for you*.

```
Wrist at rest for 1 second  →  record median ax, ay, az  →  this is "neutral"
Any future movement is measured relative to this neutral position
```

> **Adaptive Baseline:** After calibration, if you stay still, the neutral
> slowly drifts toward your current position (rate: ≈5 seconds to fully adapt).
> This helps users whose resting arm position changes due to fatigue.

### Step 2 — Tilt Extraction (Low-Pass Filter)

Gravity is a **slow, steady signal**. Arm movement creates **fast, short-lived
signals**. A **low-pass filter** lets only the slow part through.

```
alpha = 0.05  (very low → very slow filter)
smooth_ax = 0.05 × new_ax + 0.95 × old_smooth_ax
```

This effectively **separates gravity from motion**. The result `smooth_ax` is
the current gravity component — i.e., the tilt of your wrist.

### Step 3 — Gesture Rules

Once you have calibrated tilt and gyro values, simple **threshold rules**
determine the gesture:

#### Tilt → Paddle velocity (Bricks)
```
tilt_x = smooth_ax - neutral_ax    ← how far you've tilted from neutral

if |tilt_x| < 0.05g:  velocity = 0   (dead zone — stops jitter)
else:                  velocity = (tilt_x - threshold) / range   (0→1 scale)
```

#### Gyro spike → LAUNCH flick (Bricks)
```
Rolling window of last 6 gyro-Y samples (60ms)
if max(|gy|) > 200 °/s:  fire LAUNCH event  (one-shot, with 0.4s cooldown)
```

#### Gyro twist → Ball spin (Bricks)
```
if |smooth_gz| < 30°/s:  spin = 0  (dead zone)
else:  spin = (gz - 30) / 200   (−1 to +1 scale)
```

#### Slice detection → Fruit Ninja ([gesture_detector.py](file:///Users/jerold/dev/Bricks/shared/gesture_detector.py))
```
8-frame rolling window (80ms)
if peak angular velocity magnitude > 150°/s:
    classify direction from mean(gx, gy, gz)
    report SliceEvent with direction + speed
    combo_count = number of slices in last 1.5 seconds
```

### Step 4 — Functional Calibration (PCA, Phase 4)

For users with physical disabilities, the "natural" wrist motion axis may not
align with the game's horizontal axis. A **Principal Component Analysis (PCA)**
calibration finds the real motion axis:

1. User swings arm naturally for 2.5 seconds
2. Code collects `(tilt_x, tilt_y)` samples
3. PCA finds the direction of maximum variance (the swing axis)
4. A **rotation matrix** is applied to align that axis with the game's X-axis

```python
angle = ½ × atan2(2×Cxy, Cxx - Cyy)   # PCA eigenvector angle
tilt_aligned = tilt_x × cos(angle) + tilt_y × sin(angle)
```

---

## 🤖 Stage 4 — Machine Learning for Fruit Ninja ([gesture_learner.py](file:///Users/jerold/dev/Bricks/shared/gesture_learner.py))

The ML system is **only used for Fruit Ninja** slice direction classification.
The other games (Bricks, Snake) use purely rule-based detection.

### Why ML Here?

Fruit Ninja needs to know *which direction* you swiped: left, right, up, or
down. With a gyroscope, these directions create **overlapping signal patterns**
that are hard to separate with simple thresholds. A classifier can learn
personal patterns.

### The Model: Random Forest

A **Random Forest** is an ensemble of many decision trees. Each tree "votes"
on the answer, and the majority wins.

**Analogy:** Imagine 60 friends each independently look at a motion trace and
guess its direction. You take the most popular answer. If 45/60 say "right",
you're confident. If it's 32 right / 28 left, you abstain (not confident enough).

```python
RandomForestClassifier(
    n_estimators=60,   # 60 trees vote
    max_depth=8,       # each tree can be 8 levels deep
    class_weight="balanced",  # handles unequal class counts
)
```

### What Features Does the Model See? (38 features)

The model doesn't see raw sensor streams — it sees a **38-number summary** of a
~600ms window of motion around the gesture peak:

| Feature group | Count | What it captures |
|---|---|---|
| Mean/std/max per channel (gx,gy,gz,ax,ay,az) | 18 | Basic motion stats |
| Gyro magnitude mean/std/max/range | 4 | Total motion intensity |
| Dominant gyro angle | 1 | Primary rotation direction |
| Gyro + accel RMS (energy) | 2 | Overall energy |
| Jerk (rate-of-change of rotation) | 3 | Sharpness of gesture |
| Zero crossings (gz, gy) | 2 | Direction changes in motion |
| Peak timing fraction | 1 | When in window did peak occur |
| Signed area (integral gz, gy, gx) | 3 | Net directional effort |
| Dominant axis ratio | 1 | Horizontal vs vertical |
| Euler roll + pitch mean | 2 | Orientation context |
| Gyro magnitude at peak | 1 | Peak intensity |
| **Total** | **38** | |

### The Learning Pipeline

```
LEARN MODE
──────────
1. User plays Fruit Ninja normally
2. SmartRecorder watches for:
   - Is there a fruit on screen? (goal guard)
   - Is there significant motion? (>25°/s)
   - Is the motion too chaotic? (erratic guard)
   - Has enough time passed? (0.6s cooldown)
3. When all guards pass: capture 36-frame window centered on peak
4. Label = direction from cursor to nearest fruit (auto-labeled!)
5. Extract 38 features → store in JSON session file

TRAIN PHASE (after session)
──────────
1. Load all session JSON files
2. Fit RandomForestClassifier on (features, labels)
3. Save model to model.pkl

TEST MODE
──────────
1. On every frame: extract 38 features from rolling buffer
2. Ask model: predict_proba → [0.12, 0.67, 0.08, 0.13]
3. If max probability < 0.55: abstain (no prediction)
4. Else: report predicted direction
5. Smooth over last 4 frames (majority vote)
```

### Validation (Cross-Validation)

After training, you can press **V** in-game to run a background
**cross-validation** that honestly estimates how good the model is.

The key trick: **session-aware splitting**. All samples from the same play
session go to the same fold — this prevents "cheating" where the model memorizes
your style within a session instead of generalizing.

```
Sessions: A, B, C, D, E
Fold 1: train on B,C,D,E → test on A
Fold 2: train on A,C,D,E → test on B
... etc.
Reports: accuracy, precision, recall, F1, false-positive rate, abstain rate
```

---

## 📊 Summary: Which Algorithm Is Used Where?

| Gesture | Algorithm | File |
|---|---|---|
| Wrist tilt → paddle | Low-pass filter + threshold | [gesture.py](file:///Users/jerold/dev/Bricks/shared/gesture.py) |
| Wrist flick → launch | Rolling window peak detection | [gesture.py](file:///Users/jerold/dev/Bricks/shared/gesture.py) |
| Wrist twist → spin | Gyro threshold | [gesture.py](file:///Users/jerold/dev/Bricks/shared/gesture.py) |
| Orientation estimate | Madgwick AHRS (software) | [fusion_processor.py](file:///Users/jerold/dev/Bricks/shared/fusion_processor.py) |
| Orientation estimate | Bosch Kalman Filter (hardware) | [sensor.py](file:///Users/jerold/dev/Bricks/shared/sensor.py) |
| Slice direction | Random Forest (38 features) | [gesture_learner.py](file:///Users/jerold/dev/Bricks/shared/gesture_learner.py) |
| Slice detection | Angular velocity threshold | [gesture_detector.py](file:///Users/jerold/dev/Bricks/shared/gesture_detector.py) |
| Arm axis alignment | PCA rotation | [gesture.py](file:///Users/jerold/dev/Bricks/shared/gesture.py) |

---

## 🔑 Key Concepts in Plain English

| Term | Plain English |
|---|---|
| **IMU** | Inertial Measurement Unit — the combo of accel + gyro |
| **Accelerometer** | Measures force/gravity (slow, steady = tilt; fast, brief = shake) |
| **Gyroscope** | Measures spin speed in degrees per second |
| **Sensor Fusion** | Combining accel + gyro to get stable orientation |
| **Kalman / Madgwick** | Math algorithms that do sensor fusion |
| **Quaternion** | A 4-number way to represent 3D rotation without gimbal lock |
| **Euler angles** | Familiar roll/pitch/yaw degrees (simpler but can break at extremes) |
| **Low-pass filter** | Lets slow signals through, blocks fast ones (extracts gravity) |
| **Calibration** | Measuring your personal "neutral" wrist position at startup |
| **Dead zone** | A small range around zero where no gesture is reported (avoids jitter) |
| **Random Forest** | 60 decision trees each vote; majority wins |
| **Feature vector** | 38 numbers summarizing one gesture window (the model's input) |
| **Confidence threshold** | If model is < 55% sure, it abstains instead of guessing |
| **Cross-validation** | Testing the model on data it never trained on |

---

## 💡 Alternatives the Project Could Use (Not Currently Implemented)

| Approach | Pro | Con |
|---|---|---|
| **Current: Rules + RF** | Simple, interpretable, fast | RF needs labeled data; limited gestures |
| **LSTM / RNN** | Learns temporal patterns automatically | Needs much more data, harder to train |
| **1D CNN** | Good at time-series classification | Same data requirement as LSTM |
| **DTW (Dynamic Time Warping)** | Works with tiny datasets | Slow, hard to extend |
| **Hidden Markov Model** | Classic gesture recognition | Complex to tune, largely replaced |
| **On-device (MetaMotion DSP)** | Runs on sensor hardware | Limited to simple thresholds |
