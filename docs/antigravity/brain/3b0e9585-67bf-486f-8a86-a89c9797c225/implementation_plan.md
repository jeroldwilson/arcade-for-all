# MetaMotion Arcade Simplification and Standardization Plan

This plan outlines the steps to simplify the home screen (keeping only Bricks, Fruit Ninja, and Snake), implement a card-based Game Goals Selection screen matching the home screen aesthetics, standardize navigation controls across all screens, display appreciation & final score screens when exiting a game, and celebrate every 1000 points with automatic fireworks overlays.

## Proposed Changes

### Core Registry & Home Screen
#### [MODIFY] [main.py](file:///Users/jerold/dev/Bricks/main.py)
- Remove imports of `MagicWandGame` and `CalibrationGame`.
- Remove `magic_wand` and `calibration` keys from `GAME_REGISTRY`.

#### [MODIFY] [home.py](file:///Users/jerold/dev/Bricks/home.py)
- Clean up `GAMES` list to include only `["bricks", "snake", "fruit_ninja"]`.
- Modify `_compute_games` to return only the three core games.
- Remove `magic_wand` and `calibration` descriptions from `GAME_META`.
- Delete preview rendering logic (`_draw_magic_wand_preview`, `_draw_calibration_preview`).
- Clean up hints at the bottom (remove calibration short-keys).

### Shared Game Experience & Target Selection
#### [MODIFY] [shared/game_experience.py](file:///Users/jerold/dev/Bricks/shared/game_experience.py)
- Redesign `GameGoalsPrompt` to match the home screen card navigation.
  - Implement 3 horizontal cards: "INDEFINITE", "SCORE TARGET" (1000 points), and "TIME TARGET" (2 minutes).
  - Support keyboard LEFT/RIGHT navigation, mouse hover and clicks, and wrist-tilt gestures.
  - Support wrist flick (`gs.launch`), Space, Enter, or mouse click to select.
  - Pressing `ESC` returns `None` to return back to the Game Selection menu.
  - Default selection will be "INDEFINITE" for accessible (Astra) mode.
- Add `FireworksCelebration` class to render a particle-based fireworks burst on top of a frozen gameplay screen when score milestone is hit.
- Add `GameExitAppreciationScreen` class to display a styled final score and random appreciation message on game exit, with mouse click, keyboard, or gesture flick to return to menu.

#### [MODIFY] [shared/username_screen.py](file:///Users/jerold/dev/Bricks/shared/username_screen.py)
- Update `UsernameScreen.run(gesture_src)` to accept the gesture source.
- Implement left/right wrist tilt to navigate between profile rows and the "New profile" textbox.
- Implement wrist flick (`gs.launch`) to select/confirm.
- Update `ESC` key handling to return `"quit"` (exiting the application cleanly, like the top-level home screen) rather than hardcoding `"Guest"`.

### Games (Bricks, Snake, Fruit Ninja)
#### [MODIFY] [games/bricks/game.py](file:///Users/jerold/dev/Bricks/games/bricks/game.py)
- Instantiate and run `GameGoalsPrompt` inside `run()`. If it returns `None`, return `"home"`.
- Support target checks in `_update`: check if the score target (1000 points) or time target is reached.
- Inside the game loop, track and trigger `FireworksCelebration` every 1000 points, freezing updates for 2.5 seconds before resuming.
- Render the celebration overlay in `_draw` if active.
- Modify pause menu: if `key == pygame.K_x` is pressed while paused, run `GameExitAppreciationScreen` before returning `"home"`.

#### [MODIFY] [games/snake/game.py](file:///Users/jerold/dev/Bricks/games/snake/game.py)
- Add mouse/touchpad-based steering in `_update` where snake turns toward the grid cell corresponding to the mouse pointer position.
- Instantiate and run `GameGoalsPrompt` inside `run()`. If it returns `None`, return `"home"`.
- Track target limits (score/time) and end the game when reached.
- Add 1000-point celebration check to trigger fireworks and freeze gameplay updates.
- If `key == pygame.K_x` is pressed while paused, run `GameExitAppreciationScreen` before returning `"home"`.

#### [MODIFY] [games/fruit_ninja/game.py](file:///Users/jerold/dev/Bricks/games/fruit_ninja/game.py)
- Replace old `GameGoalsPrompt` run code with the new card-based goals menu.
- Support 1000-point milestone tracking to trigger `FireworksCelebration` and freeze fruit updates.
- Modify the pause menu to run `GameExitAppreciationScreen` on pressing `X`.

## Verification Plan

### Automated Tests
Currently, the workspace does not have unit tests for games. We will verify correctness via manual testing.

### Manual Verification
1. Launch the application.
2. In `UsernameScreen`, verify navigating profiles with keyboard arrows, mouse clicks, and wrist-tilts. Press `ESC` to verify clean app exit.
3. Start the game. Verify the home screen only lists Bricks, Fruit Ninja, and Snake.
4. Select a game. Confirm the Game Target Selection screen displays three cards: "INDEFINITE", "SCORE TARGET", and "TIME TARGET".
5. Verify navigation of target selection using left/right arrow keys, mouse hover, and wrist tilt. Confirm selecting "SCORE TARGET" works.
6. Verify game pauses on `ESC`. Press `X` to exit, and confirm a beautiful Final Score & Appreciation screen is displayed. Confirm you can click or flick to return to the home screen.
7. Play the game and reach 1000 points. Verify fireworks overlay displays for 2.5 seconds and then the game automatically resumes.
