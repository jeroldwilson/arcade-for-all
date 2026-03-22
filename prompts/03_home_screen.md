# Prompt: Home Screen (`home.py`)

## Task
Implement an animated game-selection menu as a `HomeScreen` class. It shows card tiles for each available game, supports gesture/keyboard/mouse navigation, and has a mode toggle button (ASTRA ↔ VEERA).

## Class interface
```python
class HomeScreen:
    def __init__(self, screen: pygame.Surface, clock: pygame.time.Clock, mode: str = "accessible"):
        ...
    def run(self, gesture_src) -> str:   # returns selected game name: "bricks" | "snake" | "calibration"
    @property
    def mode(self) -> str               # current mode string after any in-menu toggle
```

## Game list (dynamic)
```python
GAMES = ["bricks", "snake"]

def _compute_games(self) -> list:
    games = list(GAMES)
    if self.mode != "keyboard":
        games.append("calibration")   # sensor-only game
    return games
```
Store as `self._games`. Rebuild on mode toggle.

## GAME_META dictionary
Each entry has:
```python
"bricks": {
    "title":   "BRICKS",
    "desc":    ["Classic breakout.", "Tilt paddle, flick to launch.", "5 levels."],
    "desc_ac": ["Classic breakout.", "Tilt to move. Flick to launch.", "Wide paddle. No-fail mode."],
    "accent":  (80, 165, 255),   # blue
},
"snake": {
    "title":   "SNAKE",
    "desc":    ["Classic snake.", "Tilt all 4 directions.", "Eat to grow."],
    "desc_ac": ["Classic snake.", "Tilt to turn.", "Slower speed."],
    "accent":  (70, 230, 115),   # green
},
"calibration": {
    "title":   "CALIBRATE",
    "desc":    ["Live sensor orientation.", "Pitch · Roll · Yaw view.", "Sensor required."],
    "desc_ac": ["Live sensor orientation.", "Pitch · Roll · Yaw view.", "Sensor required."],
    "accent":  (255, 170, 50),   # amber
},
```

## Layout
- Cards arranged horizontally, centred in the window
- Reference window: 800×600. Scale factor `sc = min(W/800, H/600)`
- 2 cards: `CARD_W=340`, `CARD_GAP=60`, margin auto-centred
- 3 cards: reduce `card_w` to `(W - 2*margin - 2*gap) // 3` with smaller gaps
- Card height: `CARD_H=280` (scaled)
- Selected card: animated glow / brightness boost + scale pulse

## Navigation
| Input | Action |
|-------|--------|
| ← / → keyboard | Cycle selected card |
| Sensor tilt left/right | Same as arrow keys (with hold-required debounce) |
| SPACE / ENTER | Select current card |
| Flick (sensor) | Select current card |
| Mouse click on card | Select that card |
| M key | Cycle mode: accessible → standard → accessible |

## Card drawing
Each card is a rounded rect with:
- Background: dark (`#111827`) with accent-coloured top border (4px)
- Title: large bold monospace, accent colour
- Description lines: 3 lines from `desc` or `desc_ac` depending on current mode
- Preview graphic: game-specific thumbnail drawn in lower half
  - Bricks: mini paddle + ball + brick grid
  - Snake: mini grid with snake body
  - Calibration: top-down airplane silhouette over compass rose with N/E/S/W labels

## Mode toggle button
Drawn at bottom of screen:
```
[ MODE: ASTRA (Accessible) ]   or   [ MODE: VEERA (Standard) ]
```
Click or press M to cycle. On toggle:
1. Update `self._mode`
2. Rebuild `self._games = self._compute_games()`
3. Clamp `self._selected_idx` to new game count
4. Re-run `_init_layout(self._screen)`

## Gesture navigation (sensor mode)
- Track previous tilt sign; emit a card-change only on sign change crossing threshold (prevents rapid repeat)
- Hold-required: register direction only after 0.15s of sustained tilt above threshold
- Flick (`gs.launch`) → confirm selection (same as ENTER)

## Animations
- Background: slow-scrolling star field or gradient noise (optional)
- Selected card glow: pulsing brightness, period ~1.5s
- Card hover scale: selected card is 2–3% larger
- Mode button: subtle pulse when mode changes

## Resolution independence
`_init_layout(screen)` must recompute all pixel values from `sc`. Call this on startup and whenever the window is resized or fullscreen is toggled.
