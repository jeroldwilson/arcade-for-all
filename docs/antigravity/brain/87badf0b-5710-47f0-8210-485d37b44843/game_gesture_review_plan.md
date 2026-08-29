# Game Gesture Review and Optimization Plan

Based on the review of the current `Bricks`, `Snake`, and `Fruit Ninja` implementations, alongside the core `gesture.py` pipeline, here is an analysis of how gestures are currently used in Normal vs. Accessible modes, whether they are suitable, and a plan for improving them.

## 1. Game Review: Normal vs. Accessible Mode

### Bricks
*   **Normal (Veera):** Uses proportional Roll (`paddle_velocity`) to move the paddle left/right. Uses a Gyro Y peak (`launch`) to serve the ball, and Gyro Z (`spin`) to curve it.
*   **Accessible (Astra):** The game **ignores directional control**. Instead, it looks for any intent (`paddle_velocity` or `tilt_y` > 0.20). If *any* movement is detected, the game automatically calculates where the ball will land and moves the paddle there.
*   **Suitability:** Normal mode is well-mapped. Accessible mode functions essentially as a "single switch" (any movement = auto-play). While this accommodates severe spasticity, it doesn't actually let the child control *where* the paddle goes.

### Snake
*   **Normal (Veera):** Uses threshold-based Roll (`paddle_velocity`) for Left/Right and Pitch (`tilt_y`) for Up/Down.
*   **Accessible (Astra):** Similar to Bricks, the game detects *any* tilt exceeding a threshold. When triggered, it completely ignores the direction of the tilt and automatically calculates the optimal path to the food.
*   **Suitability:** Normal mode works well as a 4-way D-pad. Accessible mode again removes player agency—the player just triggers "make progress" rather than "turn left."

### Fruit Ninja
*   **Normal (Veera):** Bypasses tilt entirely and uses raw Gyroscope angular velocity (`abs_gy` and `abs_gz`) to drive an invisible cursor's X/Y speed.
*   **Accessible (Astra):** Uses the exact same gyro-to-cursor mapping but increases the multiplier and adds an "auto-aim pull" to drag the cursor towards fruits.
*   **Suitability:** Fruit Ninja actually preserves player agency in Accessible mode better than Bricks/Snake. However, using raw gyro means that spastic/involuntary tremors will result in a very jittery cursor.

## 2. Review of Existing Gesture Detection

The core `gesture.py` pipeline currently provides:
1.  **Continuous washout filter** to slowly adapt the resting neutral position.
2.  **PCA Functional Calibration** to align the physical motion axis.
3.  **Derived signals:** `paddle_velocity` (Roll), `tilt_y` (Pitch), `spin`, `launch`.

**Is it suitable for the games?**
*   **For Normal Mode:** Yes. The derived signals map perfectly to standard arcade controls.
*   **For Accessible Mode:** Partially. The washout filter helps with resting spasticity. However, because Bricks and Snake ignore directional input in Accessible mode, the gesture detection isn't actually being used to its full potential.

**Is it suitable for *learning* gestures?**
*   **Mismatch in Accessible Mode:** Currently, if you use the ML `gesture_learner.py` to learn a "Left" gesture in Accessible Snake, the game logic will ignore the "Left" prediction and just auto-steer to the food anyway. 
*   **Raw vs. Derived:** The learner currently records derived states (`paddle_velocity`). For CP patients, we should ideally be learning from the *raw* smoothed accelerometer/gyro data, because their "Left" might not cleanly map to standard Roll (`paddle_velocity`).

## User Review Required

> [!WARNING]  
> **Accessible Mode Philosophy**
> Currently, Accessible Bricks and Snake play themselves as long as the user twitches. Do we want to keep this "auto-pilot" intent-assist, or do we want to change Accessible Mode so the child actually controls the direction (using highly personalized, forgiving thresholds via ML)?

> [!IMPORTANT]
> **Machine Learning Integration**
> If we want the game to respond to personalized gestures for a CP child (e.g., their "Left" is actually a diagonal upward jerk), we must wire the ML engine's output *directly* into the game's movement logic, overriding the standard `gs.paddle_velocity`. 

## 3. Proposed Plan

If the goal is to make the existing games truly responsive to personalized gestures in Accessible mode, we should implement the following plan:

### Phase 1: Re-wire Accessible Mode Game Logic
*   **Snake:** Modify Accessible mode. Instead of auto-steering to the food on *any* movement, use the output of the ML Learner. If the learner predicts "Left" (even if the physical motion was messy), steer Left. Apply a failsafe: if they hit a wall, *then* auto-turn them.
*   **Bricks:** Modify Accessible mode to use ML predictions for "Left" and "Right" to move the paddle, rather than auto-intercepting the ball. Add a magnetic "snap-to-ball" assist only when the paddle is *near* the ball, preserving player agency.
*   **Fruit Ninja:** Implement a low-pass smoothing filter on the cursor velocity specifically for Accessible mode to reduce the impact of high-frequency tremors, while keeping the directional intent.

### Phase 2: Enhance the Gesture Learner for CP
*   Update `gesture_learner.py` to capture raw/smoothed `abs_ax`, `abs_ay`, `abs_gx`, `abs_gy` as features, rather than just the pre-calculated `paddle_velocity`. This allows the ML model to find patterns in involuntary movements that standard tilt-math destroys.
*   Introduce a **Confidence Score** output from the ML engine. 

### Phase 3: Integrate Confidence Scores
*   Update all games to read the ML confidence score. 
*   If confidence > 0.8: Execute command normally.
*   If confidence 0.4 - 0.8: Execute with heavy assistance (e.g., auto-aim, magnetic paddle).
*   If confidence < 0.4: Ignore (filters out involuntary spasms).
