---
name: bricks-game
description: >-
  Use this skill when working on the Bricks (Breakout) game: paddle control,
  ball physics, brick layout, power-ups (WIDE/MULTI/FAST), ASTRA accessible
  mode (wider paddle, wall-wrap, intent assist), ball spin mechanics, or
  score/lives system. Covers games/bricks/game.py.
---

# Bricks Game Skill

## Overview

`games/bricks/game.py` (~1003 lines) implements a classic Breakout clone with
wrist-gesture control, ball spin physics, power-ups, and full ASTRA accessibility.

## Game Mechanics

### Paddle

| Property | Standard (VEERA) | Accessible (ASTRA) |
|----------|-----------------|---------------------|
| Width | 100px | 150px |
| Speed | 560 px/s × `paddle_velocity` | Same |
| Wall behavior | Stops at edges | Wraps around screen edges |

Control: `gs.paddle_velocity` [-1..1] maps directly to paddle speed.

### Ball

| Property | Standard | Accessible |
|----------|----------|------------|
| Radius | 9px | 9px |
| Speed | 340 px/s (progressive in VEERA) | 240 px/s |
| Lives | 3 | ∞ (ball bounces off bottom) |

**VEERA progressive speed**: Ball starts at 160 px/s and ramps to 360 px/s
as score approaches `VEERA_GOAL_SCORE` (500 points).

### Ball Spin

`gs.spin` [-1..1] from wrist rotation adds lateral velocity on paddle bounce:
```python
ball.vx += gs.spin * SPIN_FACTOR  # Skilled players aim with wrist twist
```

### Bricks

- Grid: `12 × 6` bricks
- Brick size: `W/12 × 22px` with 2px gap
- Hit points: 1–3 (mapped to color: green → yellow → red)
- Power-up drop chance: 15% per destroyed brick

### Power-Ups

| Type | Effect | Duration |
|------|--------|----------|
| `WIDE` | Paddle width ×1.5 | 10 seconds |
| `MULTI` | Spawns 2 extra balls | Until balls lost |
| `FAST` | Ball speed ×1.3 | 8 seconds |

### Launch

- Ball starts attached to paddle center
- `gs.launch` (flick up) or `SPACE` key releases the ball
- Launch cooldown prevents accidental double-launch

## ASTRA Accessible Mode

Special accommodations for players with motor disabilities:

1. **Wider paddle** (150px vs 100px)
2. **Slower ball** (240 px/s vs 340 px/s)
3. **No game over**: Ball bounces off bottom wall instead of losing a life
4. **Wall-wrap paddle**: Paddle wraps around screen edges
5. **Intent assist**: Tracks sustained tilt direction and auto-steers paddle
   toward nearest ball when intent detected (`ACCESSIBLE_INTENT_THRESH = 0.20`)
6. **Spin disabled**: `twist_dead_zone = 999°/s` in CONFIG_ACCESSIBLE
7. **Bounce message**: Shows "Nice try!" for 2 seconds on bottom-wall bounces

## Resolution Independence

All coordinates use the 800×600 internal design space:
```python
sc = min(W / 800, H / 600)  # Scale factor
# All sizes multiplied by sc for rendering
```

## Key Constants (games/bricks/game.py)

```python
W, H           = 800, 600
PADDLE_W       = 100       # standard paddle width
PADDLE_H       = 14
PADDLE_Y       = H - 50    # paddle vertical position
PADDLE_SPEED   = 560       # px/s at full velocity
BALL_R         = 9
BALL_SPEED     = 340       # px/s initial (standard)
BRICK_COLS     = 12
BRICK_ROWS     = 6
LIVES_START    = 3
POWERUP_PROB   = 0.15
```

## Game Loop Structure

```python
class BricksGame:
    def __init__(self, screen, clock, debug=False, mode="standard",
                 audio=None, username="", game_submode=None):
        ...

    def run(self, gesture_src) -> str:
        # Returns "home" to go back to menu
        while True:
            dt = clock.tick(60) / 1000.0
            gs = gesture_src.get_state()
            self._handle_events()
            self._update(dt, gs)
            self._draw()
```

## Shared Module Dependencies

- `GestureHUD` — 3D hand overlay in bottom-right
- `GameGoalsPrompt` — Pre-game goal selection screen
- `InactivityMonitor` — Auto-pause on no movement
- `VisualEffects` / `StarField` / `NebulaBg` — Background and particles
- `GuidedLearnFlow` — ML learn mode integration
- `draw_gesture_debug_overlay` — Debug HUD (D key)
