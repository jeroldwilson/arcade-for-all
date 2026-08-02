# Arcade for All — Agent Context

## Project Overview
Wrist-gesture controlled pygame games powered by MbientLab MetaMotion BLE inertial sensor.
**~9,200 lines of Python** across 15 source files. Five games + home screen + ML gesture pipeline.

## Architecture
- **main.py** — Entry point, owns pygame display + clock, runs session loop
- **home.py** — Scrollable game card selection (3 visible cards, sensor tilt or keyboard nav)
- **shared/sensor.py** — BLE thread (bleak, raw GATT MetaWear protocol), streams IMUSample to queue
- **shared/gesture.py** — Gesture thread drains sensor queue, publishes GestureState via get_state()
- **shared/fusion_processor.py** — Madgwick 6-DOF AHRS (software sensor fusion fallback)
- **shared/gesture_detector.py** — SliceDetector for rapid wrist motion gestures
- **shared/gesture_learner.py** — Per-user ML model (RandomForest), learn/test/validate modes
- **shared/learn_test_support.py** — Shared HUD rendering, GuidedLearnFlow
- **shared/audio.py** — Procedural audio synthesis (numpy), no external audio files
- **shared/username_screen.py** — Profile selection/creation at startup

## Games (each in games/{name}/game.py)
- **bricks** — Breakout clone (876 lines) — tilt paddle, flick launch, spin ball
- **snake** — Grid snake (730 lines) — tilt 4-direction, flick-to-steer mode
- **fruit_ninja** — Fruit Slice (1300 lines) — gyro-driven cursor, combo system
- **calibration** — 4-panel IMU visualizer (1000 lines) — sensor-only
- **magic_wand** — Gesture tutorial (290 lines) — sensor-only

## Threading Model
1. **Main/pygame thread** — event loop, rendering, game logic
2. **BLE thread** — asyncio event loop for bleak BLE I/O (sensor.py)
3. **Gesture thread** — drains sensor queue, runs Madgwick + gesture extraction (gesture.py)
4. **Validation thread** — background cross-validation (gesture_learner.py)

## Key Data Types
- `IMUSample(ax,ay,az,gx,gy,gz,hw_heading,hw_pitch,hw_roll,hw_fusion_valid)` — sensor output
- `GestureState(paddle_velocity,launch,spin,tilt_y,calibrated,abs_*,euler_*,slice_*,steer_*,...)` — 35+ fields
- `GestureConfig(tilt_threshold,tilt_max,flick_threshold,alpha,...)` — tuning knobs

## Game Modes
- **ASTRA** (accessible) — wider paddle, slower ball, no-fail bouncing, wall-wrap, intent assist
- **VEERA** (standard) — normal rules, standard difficulty
- **Keyboard** — arrow keys replace sensor; no hardware required

## Sensor Protocol
- Talks raw BLE GATT to MetaMotion (no libmetawear dependency)
- Prefers Bosch Kalman Filter sensor fusion (module 0x19) when available
- Falls back to raw acc/gyro (modules 0x03/0x13) if SF unavailable
- Gesture pipeline: low-pass gravity filter → auto-calibrate neutral → tilt/flick/spin extraction

## ML Pipeline
- Per-user data stored in `data/gestures/{username}/`
- Learn mode: SmartRecorder with 5 quality guards → 38-feature vector → JSON sessions
- Test mode: RandomForest predictions smoothed over 4 frames with confidence abstain
- Validation: session-aware stratified k-fold CV in background thread

## Conventions & Patterns
- All games accept `(screen, clock, debug, mode, audio, username)` constructor args
- All `run(gesture_src)` methods return `"home"` to go back to menu
- Scale factor `sc = min(W/800, H/600)` used for resolution independence
- Debug HUD toggled with D key, fullscreen with F key
- Learn/test modes toggled with L/T keys; guided mode with G; validation with V

## Known Issues
- No base game class → massive code duplication across 5 games
- `get_state()` manually copies 35+ fields (fragile, add-a-field bugs)
- `sys.exit(0)` in home.py/games bypasses main.py finally block (leaks BLE)
- `_emit_sample()` called twice per frame in raw mode (stale cross-contamination)
- No BLE disconnect recovery during gameplay
- Only 1 test file (gesture_learner); core modules untested
- Excessive print() logging instead of logger.debug()
- PowerUp.draw() creates new font every frame
- Magic numbers not in GestureConfig

## File Layout
```
Bricks/
├── main.py                    Entry point
├── home.py                    Game selection
├── requirements.txt           pygame, numpy, bleak, scikit-learn
├── shared/
│   ├── sensor.py              BLE + IMU
│   ├── gesture.py             Gesture interpreter
│   ├── fusion_processor.py    Madgwick AHRS
│   ├── gesture_detector.py    Slice detection
│   ├── gesture_learner.py     ML pipeline
│   ├── learn_test_support.py  HUD helpers
│   ├── audio.py               Procedural audio
│   └── username_screen.py     Profile screen
├── games/
│   ├── bricks/game.py
│   ├── snake/game.py
│   ├── fruit_ninja/game.py
│   ├── calibration/game.py
│   └── magic_wand/game.py
├── tests/
│   └── test_gesture_learner.py
├── data/                      (gitignored)
│   ├── gestures/{username}/   ML training data
│   └── profiles/              User profiles
├── rc_car_bridge.py           Standalone ML→robot demo
└── rc_simulator.py            Visual RC car dashboard demo
```
