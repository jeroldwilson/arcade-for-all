# MetaMotion Gesture-Controlled Scratch Pad and Drone Implementation Plan

This document outlines the architecture and plan to implement the MetaMotion-based interactive gesture controller, specifically adding a new Scratch Pad game and a Drone simulation (which could later bridge to a real drone), with support for both Normal and Accessible (cerebral palsy) modes.

## Background Context
The system uses a MetaMotion wearable IMU. Currently, the architecture supports games (like bricks, snake, fruit_ninja) via a gesture processing thread (`shared/gesture.py` and `shared/fusion_processor.py`). We need to introduce a new gesture vocabulary, personalized calibration, and intent-based filtering for an Accessible mode tailored to children with motor difficulties.

## User Review Required

> [!WARNING]  
> **Accessible Mode Intent Recognition vs. Current System**
> The current gesture system (`shared/gesture.py`) exports fixed values and thresholds (e.g., `tilt_y`). To support personalized Accessible mode, we need to introduce a calibration phase and a confidence-based gesture state. This requires modifying `shared/gesture.py` and `GestureState` to expose raw intent/confidence metrics alongside traditional thresholds. Are you comfortable with modifying the core `GestureState` to include confidence scores?

> [!IMPORTANT]
> **Game Selection**
> We will create two new games in the `games/` folder: `scratch_pad` and `drone_sim`. These will need to be added to `home.py`. Should the Accessible/Normal mode toggle be globally managed in `home.py` (affecting all games) or per-game?

## Open Questions

1. **Calibration Flow:** Should calibration be a standalone "game/activity" (e.g., `games/calibration`), or a mandatory pre-game step that runs before starting *Scratch Pad* or *Drone*?
2. **Accessible Configuration:** Where should the personalized calibration data (comfortable movement ranges, noise profiles) be stored? Should it be saved to `data/profiles/{username}/accessible_profile.json`?
3. **Drone Sim vs Real Drone:** For phase 1, is it sufficient to build a purely visual Pygame drone simulation in `games/drone_sim/game.py`, similar to `rc_simulator.py`?

## Proposed Changes

### Core Sensor and Gesture Pipeline

We will enhance the existing gesture pipeline to support calibration and confidence-based intent detection.

#### [MODIFY] [`shared/gesture.py`](file:///Users/jerold/dev/Bricks/shared/gesture.py)
- **Add Calibration State:** Introduce logic to capture baseline orientation and movement ranges during a calibration phase.
- **Implement Noise Filtering:** Add low-pass filtering and moving averages for spasticity/involuntary movement handling.
- **Confidence Scoring:** Update the gesture state to include `gesture_confidence`, outputting a dictionary like `{"gesture": "FORWARD", "confidence": 0.85}` based on the user's calibrated baseline rather than absolute angles.

#### [MODIFY] [`shared/username_screen.py`](file:///Users/jerold/dev/Bricks/shared/username_screen.py) (or related profile code)
- **Add Mode Selection:** Add UI/logic to select between Normal Mode and Accessible Mode when choosing or creating a profile. Store this preference in the user's profile.

### New Games

We will implement the Scratch Pad and Drone Simulation as new Pygame modules.

#### [NEW] [`games/scratch_pad/game.py`](file:///Users/jerold/dev/Bricks/games/scratch_pad/game.py)
- **Virtual Cursor:** Implement a Pygame interface with a drawing canvas.
- **Normal Mode:** Map precise orientation (pitch/roll) to cursor movement. Deliberate forward movement activates drawing.
- **Accessible Mode:** Map directional *intent* (confidence > threshold) to smoothed cursor movement. Implement adaptive cursor speeds based on effort.
- **Features:** Free draw, pause, clear screen (via double intent). Provide rich visual and audio feedback.

#### [NEW] [`games/drone_sim/game.py`](file:///Users/jerold/dev/Bricks/games/drone_sim/game.py)
- **Drone UI:** Create a Pygame visualizer showing drone position, altitude, and orientation.
- **Normal Mode:** Full proportional control using wrist tilt for pitch/roll and wrist rotation for yaw.
- **Accessible Mode:** Simplified directional intent commands. Automatic stabilization and altitude holding.
- **Failsafes:** Implement hover-on-low-confidence logic and explicit confirmation for takeoff/landing.

#### [MODIFY] [`home.py`](file:///Users/jerold/dev/Bricks/home.py)
- Add "Scratch Pad" and "Drone Simulator" to the carousel of available games.
- Ensure the selected Accessibility mode is passed down to the games.

## Verification Plan

### Automated Tests
- If applicable, write basic logic tests for the confidence scoring algorithm to ensure involuntary spikes do not trigger high-confidence gestures. (e.g. `tests/test_gesture_confidence.py`).

### Manual Verification
1. Run the system and select Normal Mode.
2. Verify `Scratch Pad` cursor responds accurately to 1:1 wrist movements.
3. Verify `Drone Sim` responds proportionally to tilt.
4. Restart and select Accessible Mode.
5. Complete calibration (intentionally simulating restricted movement).
6. Verify that small intentional movements trigger commands, while simulated tremors/spasticity are filtered out.
7. Verify drawing stabilization (straightening) in Scratch Pad.
