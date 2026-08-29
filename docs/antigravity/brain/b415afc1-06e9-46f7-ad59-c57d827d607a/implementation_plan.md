# Scratch Pad Implementation Plan

This plan outlines the steps to create a new "Scratch Pad" game module in the Arcade for All repository. The Scratch Pad will allow users to draw lines using the MetaMotion sensor, toggle the pen with a wrist flick, change colors automatically, and test machine-learned gesture data in real-time.

## User Review Required

> [!IMPORTANT]
> - Does this align with your vision for the "Scratch Pad"?
> - The pen movement will be mapped using the sensor's Euler angles (roll and pitch), similar to the magic wand calibration game. Is this the intended control scheme?
> - "Flip to toggle pen on or off" will be mapped to the `gs.launch` property (a sharp upward wrist flick). Is this correct?

## Proposed Changes

### Games / Scratch Pad
We will create a new directory and game file for the Scratch Pad.

#### [NEW] [games/scratch_pad/game.py](file:///Users/jerold/dev/Bricks/games/scratch_pad/game.py)
- **Class `ScratchPadGame`**: Implements the standard game interface (`run(self, gesture_src)`).
- **Drawing Logic**: 
  - Track a `pen_down` boolean state.
  - Track a collection of lines (lists of `(x, y)` tuples and colors).
  - Map `gs.euler_roll` and `gs.euler_pitch` to `x, y` coordinates on the screen.
  - If `pen_down` is True, append the current `x, y` to the active line segment.
- **Flick to Toggle**: 
  - Watch for `gs.launch` (which indicates a flick).
  - On `gs.launch`, toggle `pen_down`.
  - When toggling `pen_down` to True, select a new random color for the new line segment.
- **ML Gesture Testing**:
  - Instantiate a `GestureLearningSystem` using the current `username`.
  - In the game loop, reconstruct `IMUSnapshot` objects from the current `GestureState` (using `abs_gx`, `abs_gy`, `abs_gz`, `abs_ax`, `abs_ay`, `abs_az`, `euler_roll`, `euler_pitch`) and push them into the `GestureLearningSystem`'s buffer.
  - Periodically extract features from the buffer and use `GestureModel.predict_with_confidence()` to predict the gesture.
  - If a gesture is matched confidently, display the matched gesture name on the screen (e.g., using floating text or a dedicated HUD element).

---

### Home Screen
Register the new game so it can be selected from the main menu.

#### [MODIFY] [home.py](file:///Users/jerold/dev/Bricks/home.py)
- **`GAMES` list**: Add `"scratch_pad"` to the default available games.
- **`GAME_META` dictionary**: Add title, descriptions, and an accent color for `"scratch_pad"`.
- **`_draw_preview()`**: Add a small custom preview animation for the Scratch Pad card (e.g., a simple animated drawing line).

## Verification Plan

### Manual Verification
1. Run `python main.py` and select the "Scratch Pad" game from the home menu.
2. Verify that moving the sensor moves the cursor on the screen.
3. Perform a flick gesture and verify the pen toggles ON, picking a new color.
4. Move the sensor to draw a line.
5. Perform a flick gesture to toggle the pen OFF.
6. Verify that performing gestures previously trained in Fruit Ninja (or other games) causes the predicted gesture name to appear on the screen.
