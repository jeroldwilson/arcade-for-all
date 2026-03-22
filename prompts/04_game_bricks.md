# Prompt: Bricks Game (`games/bricks/game.py`)

## Task
Implement a classic breakout-style game as a `BricksGame` class. The paddle is controlled by wrist tilt via `GestureState.paddle_velocity`. Ball is launched by wrist flick (`gs.launch`) or SPACE key.

## Class interface
```python
class BricksGame:
    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock,
                 debug: bool = False, mode: str = "standard", audio=None):
        ...
    def run(self, gesture_src) -> str:   # returns "home"
```

## Constants (reference 800×600, scale for other resolutions)
```python
W, H          = 800, 600
FPS           = 60
PADDLE_W      = 100        # px, standard mode
PADDLE_H      = 14
PADDLE_Y      = H - 50
PADDLE_SPEED  = 560        # pixels/sec at full velocity (paddle_velocity=1.0)

BALL_R        = 9
BALL_SPEED    = 340        # pixels/sec initial (level 1)

BRICK_COLS    = 12
BRICK_ROWS    = 6
BRICK_W       = W // BRICK_COLS
BRICK_H       = 22
BRICK_TOP     = 60
BRICK_GAP     = 2

LIVES_START   = 3
POWERUP_PROB  = 0.15       # chance destroyed brick drops power-up

# Accessible mode overrides
PADDLE_W_ACCESSIBLE    = 150   # 1.5× wider
BALL_SPEED_ACCESSIBLE  = 240   # slower
BOUNCE_MSG_DURATION    = 2.0   # "Nice try!" seconds
ACCESSIBLE_INTENT_THRESH = 0.20  # intent detection gate
```

## Data classes

### Brick
- `rect: pygame.Rect`, `hp: int` (1–3), `row: int`
- Colour darkens with lower HP: `factor = 0.55 + 0.45 * (hp / 3)`

### Ball
- `x, y, vx, vy: float`, `r: int`, `active: bool`
- `active=False`: ball sits on paddle waiting to launch

### PowerUp
- `rect: pygame.Rect`, `kind: str` ("WIDE" | "MULTI" | "FAST")
- Falls at 130px/s; collected when it overlaps paddle

## Paddle update (`_update_paddle`)
```python
# Standard mode — non-linear velocity curve for mid-tilt responsiveness:
if velocity != 0.0:
    velocity = math.copysign(abs(velocity) ** 0.65, velocity)
dx = velocity * paddle_spd * dt
paddle.x += int(dx)

# Mouse override: if cursor moved this frame, follow it directly (no curve)
if mouse_x != prev_mouse_x:
    paddle.centerx = mouse_x

# Launch on gesture or SPACE key
if gs.launch:
    _launch_all_inactive()
```

## Accessible mode paddle (`_update_paddle_intent`)
Instead of direct velocity, the game auto-assists using "intent" signals:
- **Ball rising**: paddle drifts randomly left/right (mimics player repositioning)
- **Ball falling**: paddle smoothly moves so ball lands at a randomised fraction of paddle width (left or right of centre — not centre, which would be too easy)
- Intent detected when `|paddle_velocity| > 0.20` or `gs.launch`

## Ball physics
- Constant speed magnitude: after each collision, renormalise `vx, vy` to preserve speed
- **Wall collisions**: left/right walls → flip vx; top wall → flip vy
- **Brick collision**: flip vy (simplistic AABB); reduce brick HP; score points; spawn power-up with `POWERUP_PROB`
- **Paddle collision**: redirect ball angle based on hit position; apply spin nudge from `gs.spin`
  - `hit_frac = (ball.x - paddle.left) / paddle.width`  → [0, 1]
  - `angle = lerp(-150°, -30°, hit_frac)` (upward)
  - Spin adds up to ±30px/s lateral boost
- **Missed ball (below paddle)**:
  - Standard: lose a life; respawn ball on paddle
  - Accessible: ball bounces back up from bottom edge (no life lost), show "Nice try!" message

## Ball launch
```python
def _launch_all_inactive(self):
    angle = random.uniform(-65, -115)   # upward, slight randomness
    rad   = math.radians(angle)
    speed = ball_spd + (level - 1) * int(20 * scale)   # speed grows per level
    ball.vx = speed * math.cos(rad)
    ball.vy = speed * math.sin(rad)
    ball.active = True
```
Ball inherits paddle position at launch (sits on paddle while inactive).

## Power-ups
| Kind | Effect | Duration |
|------|--------|----------|
| WIDE | Paddle 2× wider | 10s |
| MULTI | Spawn 2 extra balls | permanent until lost |
| FAST | Ball speed ×1.4 | permanent for that ball |

## Levels (5 total)
- Level 1: all 1-HP bricks
- Level 2: 40% chance of 2-HP bricks
- Level 3+: 25% chance of 3-HP, 40% chance of 2-HP
- Each level: ball spawns ~20px/s faster (capped at BALL_SPEED_ACCESSIBLE in accessible mode)
- Win condition: all bricks destroyed → advance to next level
- Level 5 clear → YOU WIN screen

## Controls
| Input | Action |
|-------|--------|
| Sensor tilt L/R | Move paddle |
| Sensor flick up | Launch ball |
| Sensor twist CW/CCW | Ball spin (Bricks only) |
| ← / → | Move paddle (keyboard) |
| SPACE | Launch ball |
| ESC | Pause / back to menu (when game over) |
| R | Restart (game over / win screen) |
| D | Toggle debug HUD |
| F | Toggle fullscreen |

## Debug HUD
When enabled, overlay in top-right corner:
```
tilt:  +0.23 g
vel:   +0.61
gy:   +145 °/s
spin:  +0.38
```

## Resolution independence
`_init_layout(screen)` computes all px values from `sc = min(W/800, H/600)`. Ball/paddle are in pixel space — toggle fullscreen resets game state.
