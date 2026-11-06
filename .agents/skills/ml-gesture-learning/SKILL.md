---
name: ml-gesture-learning
description: >-
  Use this skill when working on the machine learning gesture recognition
  pipeline: per-user model training, SmartRecorder quality guards, 38-feature
  extraction, RandomForest classification, temporal smoothing, cross-validation,
  learn/test mode HUD, or gesture data storage. Covers shared/gesture_learner.py
  and shared/learn_test_support.py.
---

# ML Gesture Learning Skill

## Overview

`shared/gesture_learner.py` (~1021 lines) implements a **per-user personalized gesture
recognition pipeline** using scikit-learn RandomForest. It learns each user's unique
movement patterns (including accommodations for motor disabilities) from in-game play.

## Architecture

```
GestureLearningSystem (top-level coordinator)
├── GestureBuffer          ← rolling deque of 60 IMUSnapshot frames (~1s)
├── SmartRecorder          ← event-centered recording with 5 quality guards
│   ├── FeatureExtractor   ← 38-feature vector from IMU window
│   └── IntentLabeler      ← direction label from blade→fruit geometry
├── GestureDataset         ← versioned JSON session storage (data/gestures/{username}/)
├── GestureModel           ← RandomForest with confidence-based abstain
└── GestureValidator       ← session-aware stratified k-fold CV (background thread)
```

## Data Flow

```
Real-time IMU → GestureBuffer (60-frame deque)
                    │
                    ▼
              SmartRecorder.try_record()
                    │ ← 5 quality guards gate recording
                    ▼
              FeatureExtractor.extract() → 38-float vector
                    │
                    ▼
              IntentLabeler.label() → "left"|"right"|"up"|"down"|None
                    │
                    ▼
              GestureDataset.save_session() → JSON file in data/gestures/{user}/
                    │
                    ▼
              GestureModel.train() → RandomForestClassifier
                    │
                    ▼
              GestureModel.predict() → (label, confidence)
                    │ ← temporal smoothing (4-frame majority vote)
                    ▼
              GestureLearningSystem.get_gesture() → final label or None
```

## SmartRecorder Quality Guards

Recording only fires when ALL guards pass:

| Guard | Check | Purpose |
|-------|-------|---------|
| **Goal guard** | `fruits_xy` is non-empty | Only record when targets visible |
| **Motion guard** | `gyro_mag >= motion_mag_min` | Ignore stillness |
| **Cooldown guard** | `time - last_rec >= cooldown_secs` | Prevent duplicates |
| **Erratic guard** | `gyro_std <= erratic_std_max` | Reject random shaking |
| **Balance guard** | `max_class / min_class < 3.0` | Warn on class imbalance |

### Event Centering

Instead of fixed windows, recordings are **centered on the motion peak**:
```python
peak_idx = argmax(gyro_magnitudes)
centered_window = buffer[peak_idx - 18 : peak_idx + 18]  # EVENT_FRAMES = 36
```

## 38-Feature Vector (FeatureExtractor)

| Index | Features | Count |
|-------|----------|-------|
| 0-17 | Per-channel mean/std/max_abs for gx,gy,gz,ax,ay,az | 18 |
| 18-21 | Gyro magnitude: mean, std, max, range | 4 |
| 22 | Dominant gyro angle: `atan2(mean_gy, mean_gz)` | 1 |
| 23-24 | Gyro RMS, accel RMS (energy) | 2 |
| 25-27 | Jerk: abs mean of frame-to-frame diffs (gx,gy,gz) | 3 |
| 28-29 | Zero crossings: gz, gy | 2 |
| 30 | Peak timing fraction: `peak_idx / (n-1)` | 1 |
| 31-33 | Signed area: `sum(gz)`, `sum(gy)`, `sum(gx)` | 3 |
| 34 | Dominant axis ratio: `|gz| / (|gz| + |gy| + ε)` | 1 |
| 35-36 | Euler roll mean, pitch mean | 2 |
| 37 | Gyro magnitude at peak frame | 1 |
| **Total** | | **38** |

### Feature Selection Rationale

**USE:** `abs_gx/gy/gz` (primary motion), `abs_ax/ay/az` (orientation), `av_magnitude`,
`euler_roll/pitch` (gravity-referenced)

**REJECT:** `euler_yaw` (drifts), `qw/qx/qy/qz` (redundant), `slice_active/direction` (leaky),
`paddle_velocity/launch/spin` (downstream signals), `raw_ax/raw_gz` (redundant)

## IntentLabeler

Labels gestures by **blade-to-fruit geometry**:
1. Find nearest fruit to blade position
2. Compute direction vector (dx, dy)
3. Require dominant axis ≥ 75% (`ambiguity_margin = 0.25`)
4. Reject if blade trajectory moves opposite to fruit
5. Returns `"left"` | `"right"` | `"up"` | `"down"` | `None`

## GestureModel (RandomForest)

```python
RandomForestClassifier(
    n_estimators=80,
    max_depth=10,
    min_samples_leaf=3,
    class_weight="balanced",
    random_state=42,
)
```

### Inference with Confidence Abstain
- `predict_proba()` → if `max_prob < confidence_threshold` → abstain (return None)
- Standard threshold: 0.55; Accessible: 0.45
- **Temporal smoothing**: majority vote over last `smoothing_frames` (4 standard, 6 accessible)

## Accessibility Profiles

```python
PROFILE_STANDARD = GestureProfile(
    dead_zone=15.0, confidence_threshold=0.55, smoothing_frames=4,
    motion_mag_min=25.0, erratic_std_max=180.0, ambiguity_margin=0.25,
    cooldown_secs=0.6
)

PROFILE_ACCESSIBLE = GestureProfile(
    dead_zone=6.0, confidence_threshold=0.45, smoothing_frames=6,
    motion_mag_min=12.0, erratic_std_max=999.0, ambiguity_margin=0.0,
    cooldown_secs=1.5
)
```

Key accessible adaptations:
- `erratic_std_max=999.0`: Accepts tremors/spasms as valid gestures
- `ambiguity_margin=0.0`: Allows diagonal/arcing motions
- `motion_mag_min=12.0`: Triggers on very weak movements

## GestureValidator (Background Thread)

Session-aware stratified k-fold cross-validation:
- Runs in a background thread so UI stays responsive
- Groups by `session_id` to prevent data leakage across sessions
- Reports precision, recall, F1, and false-positive rate per class
- Triggered by pressing `V` key in test mode

## Data Storage

```
data/gestures/{username}/
├── session_20240829_143000_abc123.json  ← one per learning session
└── model.pkl                            ← serialized trained model
```

Each session JSON:
```json
{
  "schema_version": 2,
  "session_id": "abc123",
  "records": [
    {
      "features": [38 floats],
      "label": "right",
      "quality": {"gyro_peak": 280.5, "gyro_mean": 120.3, "gyro_std": 65.2},
      "mode": "standard"
    }
  ]
}
```

## In-Game Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `L` | Toggle learn mode (start recording gestures) |
| `T` | Toggle test mode (use trained model for control) |
| `G` | Toggle guided/manual learn mode |
| `V` | Show validation panel (in test mode) |

## Learn/Test HUD (learn_test_support.py)

- `draw_gesture_debug_overlay()`: Real-time sensor values overlay
- `draw_submode_indicator()`: Shows LEARN/TEST/GUIDED mode badge
- `draw_validation_panel()`: CV results table overlay
- `GuidedLearnFlow`: Step-by-step guided recording with arrow prompts
- `build_validation_lines()`: Formats CV metrics for display
