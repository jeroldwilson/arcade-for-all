# Prompt: Calibration Game (`games/calibration/game.py`)

## Task
Implement a sensor-orientation visualizer as a `CalibrationGame` class. It helps users understand how the MetaMotion wrist sensor maps to pitch, roll, and yaw by showing live aviation-style instrument panels. Only available when a real sensor is connected (mode ≠ "keyboard").

## Class interface
```python
class CalibrationGame:
    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock,
                 debug: bool = False, mode: str = "standard", audio=None):
        ...
    def run(self, gesture_src) -> str:   # returns "home"
```

## Screen layout — 4 equal panels (2×2 grid)
```
┌─────────────────┬─────────────────┐
│  FRONT VIEW     │  SIDE VIEW      │
│  Roll indicator │  Pitch indicator│
│  (circular AI)  │  (circular AI)  │
├─────────────────┼─────────────────┤
│  TOP VIEW       │  SENSOR DATA    │
│  Yaw / Heading  │  Numeric table  │
│  (compass rose) │  + controls     │
└─────────────────┴─────────────────┘
```
Each panel occupies exactly 1/4 of the screen. All sized dynamically.

## Angle calculations
```python
ax, ay, az = gs.abs_ax, gs.abs_ay, gs.abs_az   # smoothed accel (g)
gx, gy, gz = gs.abs_gx, gs.abs_gy, gs.abs_gz   # raw gyro (°/s)

pitch_deg = math.degrees(math.atan2(-ax, math.sqrt(ay**2 + az**2)))
roll_deg  = math.degrees(math.atan2(ay, az))
yaw_deg  += gz * dt   # integrated; reset to 0 with SPACE
yaw_deg   = yaw_deg % 360.0
```

## Panel 1 — Front View (Roll / Attitude Indicator)
- Draw a **circular attitude indicator** (AI):
  - Background circle split into sky (blue `#4a7fc1`) and ground (brown `#8B6914`)
  - Ground polygon rotates by `roll_deg` around circle centre
  - Fixed airplane front-view silhouette (horizontal wing line + fuselage dot) drawn on top of circle — does NOT rotate
  - Circle clipping: use SRCALPHA surface + white circle mask with `BLEND_RGBA_MULT`
- Label below: `Roll: +12.5°`

### Drawing the rotated ground
```python
# Draw rotated half-rectangle polygon for ground (lower half of circle, rotated)
def _draw_ai_circle(surf, cx, cy, r, roll_rad, pitch_offset_px):
    # 1. Fill entire circle area with sky colour
    # 2. Compute polygon for lower half-circle rotated by roll_rad
    # 3. Fill polygon with ground colour
    # 4. Apply circular mask (SRCALPHA + BLEND_RGBA_MULT)
```

## Panel 2 — Side View (Pitch / Attitude Indicator)
- Same circular AI but horizon shifts **vertically** instead of rotating
  - `pitch_offset_px = pitch_deg * (r / 70.0)`  (scale so ±70° fills the circle)
  - Positive pitch → horizon moves up (sky expands)
- Fixed side-profile airplane silhouette (fuselage line + wing + tail) on top
- Label: `Pitch: -5.8°`

## Panel 3 — Top View (Yaw / Heading)
- **Compass rose** drawn on a dark circle:
  - Thin tick marks every 10° (short), every 30° (medium), every 90° (long)
  - Cardinal labels N/E/S/W at top/right/bottom/left respectively (N always at top)
  - Intermediate labels NE/SE/SW/NW (smaller font)
- **Airplane top-down silhouette** rotates with yaw:
  - Fuselage: narrow rounded rectangle pointing up (0°)
  - Wings: wide thin rectangle crossing fuselage
  - Tail: smaller rectangle at rear
  - Rotation: `math.radians(yaw_deg - 90)` (−90 because 0° = East in math, North in display)
- Label: `Yaw: 045.2°  (SPACE=reset)`

## Panel 4 — Sensor Data
Plain text table on dark background:
```
  Computed Angles
  ───────────────
  Pitch   -5.8°
  Roll   +12.5°
  Yaw     45.2°

  Accelerometer (g)
  ───────────────
  ax     +0.213
  ay     -0.042
  az     +0.976

  Gyroscope (°/s)
  ───────────────
  gx     +2.1
  gy     -8.4
  gz    +12.7

  ─────────────────
  ESC  → home
  SPACE → reset yaw
```

## Calibrating overlay
While `gs.calibrated == False`, draw semi-transparent dark overlay over entire screen with centred message:
```
⚙  CALIBRATING…
Hold sensor still
```

## Controls
| Key | Action |
|-----|--------|
| ESC / BACKSPACE | Return to home |
| SPACE / R | Reset yaw accumulator to 0° |
| F | Toggle fullscreen |
| D | No-op (no debug HUD needed here) |

## Implementation notes

### Circular clipping (pygame has no native circle clip region)
```python
# 1. Draw sky/ground on SRCALPHA surface
layer = pygame.Surface((r*2, r*2), pygame.SRCALPHA)
# ... draw sky rect, ground polygon ...

# 2. Create white circle mask
mask = pygame.Surface((r*2, r*2), pygame.SRCALPHA)
pygame.draw.circle(mask, (255,255,255,255), (r, r), r)

# 3. Apply mask: pixels outside circle → alpha=0
layer.blit(mask, (0,0), special_flags=pygame.BLEND_RGBA_MULT)

# 4. Blit onto main surface
surf.blit(layer, (cx-r, cy-r))
```

### Yaw drift
The sensor has no magnetometer in this integration. `gz * dt` integration drifts over time. Document this as expected behaviour; SPACE resets.

### Frame rate
Run at `FPS=60`. `dt = clock.tick(FPS) / 1000.0` used for yaw integration.

## Availability
Only show in home screen when `mode != "keyboard"`. In `home.py`, the `_compute_games()` method adds `"calibration"` to the game list only when sensor is active.
