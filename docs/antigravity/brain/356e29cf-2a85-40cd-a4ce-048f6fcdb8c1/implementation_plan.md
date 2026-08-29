# Gameplay Experience & Accessibility Enhancements

Based on your feedback, we are holding off on the previous plan and pivoting to a new set of highly engaging, interactive features designed to keep kids motivated and excited.

As requested, the plan prioritizes the most important feature (inactivity feedback and its dependencies) before detailing the general gameplay experience improvements.

## User Review Required
Please review the proposed plan below. If this aligns with your vision, approve it and I will begin implementation immediately, starting with the sensor dependencies.

## Open Questions
> [!IMPORTANT]
> - Should the **Game Goals Prompt** appear every single time a game starts, or only once when they launch the app/select a game?
> - For the **Fireworks effect**, would you like procedural particle effects (drawn on the fly) or do you have sprite assets you'd prefer to use? (Procedural is easier to implement immediately).

---

## 1. Most Important Feature: Inactivity Feedback

If a child slows down or stops making moves, the game will try to recapture their attention using multi-sensory feedback.

### Dependencies & Sensor Upgrades
- **LED Colors:** Modify `shared/sensor.py` to support specifying LED color channels (Green=0, Red=1, Blue=2). Currently, it only supports solid green. We will add a `blink_led(color="random", pattern="blink")` method.
- **Haptic Control:** Leverage the existing `vibrate(duration)` method in `MetaMotionSensor`, but add a background task to pulse it intermittently when inactive.

### Implementation: The "Wake Up" Sequence
- **Inactivity Timer:** We will track `time_since_last_motion` in the main game loop (`game.py`). 
- **Trigger:** If inactive for `X` seconds (e.g., 5 seconds):
  1. **Haptics:** Send intermittent vibration pulses to the sensor.
  2. **LEDs:** Blink the sensor's LED in random colors.
  3. **Screen:** Flash a random encouraging message prominently on the screen (e.g., *"Come on, {username}, you can do it!"*, *"Keep going {username}!"*).

---

## 2. Gameplay Experience Improvements

Once the core feedback loop is established, we will add the structural and visual gameplay improvements.

### Game Goals Prompt
- **Setup Screen:** Before the game starts, insert a new configuration screen that asks the user to pick their goal:
  - **Score Target:** e.g., First to 50 / 100 points.
  - **Time Limit:** e.g., 2 min, 5 min, 10 min.
  - **Indefinite:** Endless play.
- **Support:** This will be added to the base game initialization so it works for all games (Fruit Ninja, Bricks, Snake) in both Astra (Accessible) and Veera modes.

### Auto-Pause & Resume
- **Pause Trigger:** If inactivity continues past the "Wake Up" sequence (e.g., 15 seconds of no motion), the game will automatically enter a paused state.
- **Resume Trigger:** The moment the sensor detects a gesture/movement spike, the game will automatically unpause.
- **Effects:** Add a satisfying "whoosh" sound and visual dimming on pause, and an energetic burst/sound on resume.

### Celebration & Effects (Fireworks)
- **Point Gain:** Add a small visual pop/sparkle effect around the cursor/paddle whenever a point is scored.
- **Game Over/Victory:** Implement a procedural **Fireworks Particle System**.
- **Sensory Celebration:** Sync the on-screen fireworks with the sensor! When fireworks explode on screen, the sensor will vibrate and flash random colored LEDs to celebrate the child's achievement.

### Seamless Learning Flow
- **Continuous Play:** Modify the `gesture_learner.py` guided flow. Instead of returning to the home menu after a learning session finishes, it will seamlessly prompt to "Start Playing" and flow directly into the accessible game mode.
