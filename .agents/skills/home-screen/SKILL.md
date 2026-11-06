---
name: home-screen
description: >-
  Use this skill when adding a new game to the menu, modifying the home
  screen carousel, changing game card layout, adjusting navigation
  (tilt/keyboard/mouse), or updating the GAMES list and GAME_META dict.
  Covers home.py and the game registration pattern in main.py.
---

# Home Screen Skill

## Overview

`home.py` (~653 lines) implements a scrollable game selection carousel. It renders
3 visible game cards at a time with sensor tilt navigation, keyboard arrows, or
mouse hover/click.

## Game Registration (How to Add a New Game)

Adding a new game requires changes in **two files**:

### Step 1: `home.py` — Add to GAMES list and GAME_META dict

```python
# Line ~40: Add game ID to GAMES list (order = display order)
GAMES = ["fruit_ninja", "bricks", "snake", "your_game", ...]

# Line ~42+: Add metadata entry
GAME_META = {
    ...
    "your_game": {
        "title":   "YOUR GAME",                         # Card title (uppercase)
        "desc":    ["Line 1!", "Line 2.", "Line 3."],   # Standard mode descriptions
        "desc_ac": ["Line 1!", "Line 2.", "Line 3."],   # ASTRA accessible descriptions
        "accent":  (R, G, B),                           # Card accent color tuple
    },
}
```

### Step 2: `main.py` — Import and register in GAME_REGISTRY

```python
# Line ~272+: Import
from games.your_game.game import YourGame

# Line ~278+: Add to GAME_REGISTRY dict
GAME_REGISTRY = {
    ...
    "your_game": YourGame,
}
```

### Step 3: Create the game module

```
games/your_game/
├── __init__.py     # Empty or import
└── game.py         # Must follow the game constructor pattern (see game-conventions rule)
```

## Home Screen Architecture

```
HomeScreen
├── __init__(screen, clock, mode, username, debug)
├── _compute_games()         ← builds game list + conditionally adds sensor-only games
├── _init_layout(screen)     ← responsive card sizing based on sc = min(W/800, H/600)
├── _update_card_rects()     ← positions visible card Rects with scroll offset
├── run(gesture_src) → str   ← blocks until game selected, returns game ID or "quit"
│   ├── _handle_events()     ← keyboard, mouse, quit
│   ├── _handle_sensor()     ← tilt navigation + flick selection
│   └── _draw()              ← nebula bg, cards, title, hints, mode toggle, HUD
└── mode                     ← "standard" | "accessible" (toggled with A key)
```

## Card Layout

```
┌─────────────────────────────────────────┐
│            ARCADE FOR ALL               │  ← Title at top
│                                          │
│   ┌────────┐  ┌────────┐  ┌────────┐   │  ← 3 visible cards
│   │ Game 1 │  │ Game 2 │  │ Game 3 │   │
│   │        │  │ (sel)  │  │        │   │
│   └────────┘  └────────┘  └────────┘   │
│                                          │
│  ◄ ● ● ● ● ●  ►                        │  ← Scroll dots
│                                          │
│  [ASTRA] / [VEERA]  mode toggle         │  ← Bottom
│  ←/→ navigate  SPACE/↑ select           │  ← Hints
└─────────────────────────────────────────┘
```

- `VISIBLE_CARDS = 3` (maximum cards shown at once)
- `CARD_W = 200`, `CARD_H = 300`, `CARD_GAP = 20`, `CARD_Y = 130`
- All dimensions scale by `sc = min(screen_w/800, screen_h/600)`
- Scroll offset tracks the leftmost visible card index

## Navigation Controls

### Sensor (tilt)
- Tilt left/right past `TILT_THRESHOLD` (0.55) → navigate cards
- Cooldown: `TILT_NAV_CD` (1.20s) between moves
- Accelerometer hold: `ACC_HOLD_REQUIRED` (0.35s) sustained tilt
- Flick up (launch gesture) → select highlighted card

### Keyboard
- `←` / `→` → navigate cards
- `ENTER` / `SPACE` → select
- `ESC` → quit
- `A` → toggle ASTRA/VEERA mode
- `D` → toggle debug HUD
- `F` → toggle fullscreen

### Mouse
- Hover over card → highlight
- Click → select

## Mode Toggle

The home screen shows `[ASTRA]` or `[VEERA]` mode badge:
- `A` key toggles `self.mode` between `"accessible"` and `"standard"`
- Mode is propagated to game constructors and gesture config

## Sensor-Only Games

`calibration` and `magic_wand` are **only** added to the game list when a sensor
is connected (checked by `gesture_src` type). They don't appear in keyboard-only mode.

## GestureHUD Integration

The home screen renders a `GestureHUD` overlay in the bottom-right corner,
showing real-time hand orientation and gesture feedback.
