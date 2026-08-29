# Walkthrough - Inactivity Animation Feature

I have successfully implemented the animated wake-up character feature for Astra mode and addressed the follow-up requirements:
1. Ensured the wake-up prompt stays visible for a minimum of 10 seconds.
2. Removed the semi-transparent black background card, making the entire animation and message layout fully transparent.

## Changes Made

### 1. Asset Generation & Processing
* Generated a cartoon mango character with waving hand, arms, and legs.
* Stripped out the checkerboard background to make a transparent PNG.
* Saved the final image to `assets/images/mango_character.png`.

Here is the transparent character:
![Mango Character](file:///Users/jerold/.gemini/antigravity-ide/brain/c70a743e-c73d-4e21-ba67-04a14e59efc1/mango_character.png)

---

### 2. Inactivity Animation and Layout Logic
Modified `InactivityMonitor` in [`shared/game_experience.py`](file:///Users/jerold/dev/Bricks/shared/game_experience.py#L371-L477):
* **10-Second Duration**: Added a `wake_up_trigger_time` tracker. When the user moves, if the wake-up message has been active for less than 10.0 seconds, it will remain visible until the 10-second mark is reached, preventing it from flashing and disappearing on brief movements or sensor noise.
* **Waving & Breathing Transformations**:
  * **Waving**: The sprite's rotation oscillates sinusoidally between `-12°` and `+12°` at 6Hz.
  * **Breathing**: The sprite scales dynamically up and down between `95%` and `105%` scale at 3Hz.
* **Transparent Layout**:
  * Removed the dark background card overlay from both the character layout and text-only fallback layout, rendering the animated mango and message directly over the game screen.

---

## Verification Results
* Run the game and enter Astra mode. 
* Trigger inactivity by not moving. The transparent waving mango and motivational message will appear directly on top of the game screen.
* Move the sensor briefly; the animation stays active on the screen for at least 10 seconds.
