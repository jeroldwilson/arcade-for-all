# Prompt: Snake Game (`games/snake/game.py`)

## Task
Implement a classic grid-based Snake game as a `SnakeGame` class. The snake direction is controlled by wrist tilt in 4 directions using `GestureState.paddle_velocity` (left/right) and `GestureState.tilt_y` (forward/back).

## Class interface
```python
class SnakeGame:
    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock,
                 debug: bool = False, mode: str = "standard", audio=None):
        ...
    def run(self, gesture_src) -> str:   # returns "home"
```

## Constants
```python
W, H          = 800, 600
FPS           = 60
CELL           = 20         # grid cell size (px)
COLS           = W // CELL  # 40
ROWS           = H // CELL  # 30

MOVE_INTERVAL  = 0.12       # seconds per step (standard)
TILT_THRESH    = 0.35       # GestureState threshold for direction change

# Accessible mode
MOVE_INTERVAL_ACCESSIBLE = 0.50   # slower steps
ACCESSIBLE_GESTURE_CD    = 0.80   # seconds between direction changes
```

## Grid & Snake
- Snake stored as `deque` of `(col, row)` tuples, head at front
- Direction: `(dc, dr)` tuple, default `(1, 0)` = right
- On each step: new head = head + direction; if food → grow (don't pop tail); else pop tail
- Wrap-around walls: snake exits left → appears right, etc.
- Self-collision: if new head in body → game over

## Direction control

### Standard mode
Any frame where tilt or key changes direction:
```python
if paddle_velocity < -TILT_THRESH: try_turn(LEFT)
if paddle_velocity > +TILT_THRESH: try_turn(RIGHT)
if tilt_y < -TILT_THRESH:          try_turn(UP)
if tilt_y > +TILT_THRESH:          try_turn(DOWN)
```
`try_turn` rejects 180° reversals (can't reverse into yourself).

### Accessible mode
Same logic but with `gesture_cooldown = 0.80s` between accepted direction changes. This prevents accidental rapid turns.

### Keyboard override (always active)
Arrow keys map to UP/DOWN/LEFT/RIGHT — take priority when pressed.

## Food
- Single food pellet at random grid position (not on snake body)
- When eaten: grow snake, spawn new food, increment score
- Every 5 foods: `MOVE_INTERVAL *= 0.90` (speed up), capped at min interval

## Scoring
- +10 per food eaten
- Score displayed top-left

## Visual design
- Dark background `(15, 15, 25)`
- Snake: gradient green head → body; head is brighter
- Food: bright red circle, subtle glow
- Grid lines: very faint (optional toggle)
- Game over: semi-transparent overlay with score and instructions

## Controls
| Input | Action |
|-------|--------|
| Sensor tilt L/R | Turn left/right |
| Sensor tilt forward/back | Turn up/down |
| ← / → / ↑ / ↓ | Keyboard direction |
| ESC | Pause / back to menu (game over) |
| R | Restart (game over) |
| D | Toggle debug HUD |
| F | Toggle fullscreen |

## Debug HUD
When enabled, overlay:
```
tilt_x: +0.23 g  → RIGHT
tilt_y: -0.41 g  → UP
vel:    +0.61
```

## Resolution independence
`_init_layout(screen)` recomputes `CELL` scaled by `sc`. Grid is re-derived from screen dimensions. On fullscreen toggle, reset snake to starting position.

## Accessible mode notes
- Slower move interval gives more time to react
- Gesture cooldown prevents accidental rapid direction changes from wrist tremor
- No game-over on wall collision (optional: wrap-around always enabled in accessible mode)
