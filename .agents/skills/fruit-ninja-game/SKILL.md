---
name: fruit-ninja-game
description: >-
  Use this skill when working on the Fruit Ninja / Fruit Slice game: gyro
  cursor control, fruit spawning and physics, slicing detection and combos,
  katana trail rendering, dynamic fruit sizes, shuffle-bag spawner, bomb
  hazards, ASTRA auto-aim, or the score/timer system. Covers
  games/fruit_ninja/game.py, shared/assets.py, and shared/gameplay_config.py.
---

# Fruit Ninja Game Skill

## Overview

`games/fruit_ninja/game.py` (~1446 lines) implements a Fruit Slice game where
fruits arc upward from the bottom and the player slices them with wrist
gestures driving a gyro-mapped cursor.

## Cursor / Blade Control

### Sensor Mode (gyro → cursor velocity)

```python
# Raw gyro °/s drives cursor speed:
cursor_x += abs_gz * GYRO_SCALE_X   # yaw → horizontal
cursor_y -= abs_gy * GYRO_SCALE_Y   # pitch → vertical (up = up)
```

Tuning constants (from `shared/gameplay_config.py`):

| Param | Standard (VEERA) | Accessible (ASTRA) |
|-------|-----------------|---------------------|
| `gyro_scale_x` | Config-driven | Config-driven (higher) |
| `gyro_scale_y` | Config-driven | Config-driven (higher) |
| `gyro_dead` | ~15°/s | ~6°/s |
| `gyro_visible` | ~25°/s | ~12°/s |
| `gyro_slice` | ~40°/s | ~20°/s |
| `auto_aim_pull` | N/A | Active — soft magnetism |

### Keyboard Mode
- Mouse position = blade position
- Moving mouse over fruits slices them
- `MOUSE_MOVE_PX = 4` minimum movement threshold

### Cursor Visibility
- Cursor/trail only appears when hand is moving above `gyro_visible` threshold
- Fades after `CURSOR_HIDE_MS` (300ms) of stillness

## Fruit Spawning

### Fruit Catalog (shared/assets.py)

Each fruit has a `size_multiplier` for visual scale:

| Fruit | Multiplier | Notes |
|-------|-----------|-------|
| 🍉 Watermelon | 2.0× | Largest target |
| 🍍 Pineapple | 1.5× | |
| 🥭 Mango | 1.25× | |
| 🍊 Orange | 1.0× | Base size |
| 🍎 Apple | 1.0× | |
| 🍑 Peach | 1.0× | |
| 🥝 Kiwi | 0.9× | |
| 🍓 Strawberry | 0.75× | |
| 🍒 Cherry | 0.75× | Smallest target |

### Shuffle-Bag Spawner

Guarantees all fruit types appear in fair rotations:
```python
self._fruit_bag = list(FRUIT_CATALOG.keys())  # 8-9 fruits
random.shuffle(self._fruit_bag)
# Pop one per spawn; refill & reshuffle when empty
```
This prevents Pineapple/Watermelon from being starved by random spawning.

### Physics

```python
GRAVITY = 380.0  # px/s² downward

# Fruits launch from bottom with random upward velocity
fruit.vy = -random.uniform(500, 700)  # initial upward speed
fruit.vx = random.uniform(-100, 100)  # lateral drift
# Peak height ≈ vy² / (2 × GRAVITY) ≈ 550px (93% of screen)
```

## Slicing

A fruit is sliced when:
1. Blade cursor overlaps fruit hitbox (radius-based collision)
2. Blade speed exceeds `gyro_slice` threshold (cursor must be moving)
3. OR: ASTRA auto-aim pulls cursor to nearest fruit

### Dynamic Hit Zones

Collision radius scales with `size_multiplier`:
```python
hit_radius = base_radius * FRUIT_CATALOG[fruit_type].size_multiplier
```

### Combo System

- Consecutive slices within ~1.5s build combo multiplier
- Higher combos trigger `ComboFlash` visual effects
- Score: `base_points × combo_multiplier`

## Visual Effects (from shared/game_experience.py)

| Effect | Class | Trigger |
|--------|-------|---------|
| Blade trail | `KatanaTrail` | Cursor movement |
| Juice splatter | `JuiceSplatter` | Fruit sliced |
| Combo flash | `ComboFlash` | 3+ combo |
| Fireworks | `FireworksCelebration` | Score milestones |

## ASTRA Accessible Mode

1. **Slower fruit arcs**: Reduced launch velocity and gravity
2. **Larger hitboxes**: Expanded collision radius
3. **Auto-aim**: Soft magnetism pulls cursor toward nearest fruit
   (`AUTO_AIM_PULL` factor)
4. **No lives / no bombs**: 60-second timed session, no penalties
5. **Lower gyro thresholds**: Weaker wrist movements register as slices
6. **InactivityMonitor**: Encouragement messages + auto-pause

## Game Modes

| Mode | Timer | Lives | Bombs | Speed |
|------|-------|-------|-------|-------|
| ASTRA (accessible) | 60s countdown | ∞ | No | Slow |
| VEERA (standard) | 60s countdown | 3 | Yes | Normal |

## Key Imports

```python
from shared.gameplay_config import FRUIT_NINJA_ACCESSIBLE, FRUIT_NINJA_STANDARD
from shared.assets import load_sprite, FRUIT_CATALOG
from shared.game_experience import (
    GameGoalsPrompt, InactivityMonitor, VisualEffects,
    NebulaBg, KatanaTrail, JuiceSplatter, ComboFlash,
    GameExitAppreciationScreen, FireworksCelebration,
)
```

## ML Learn/Test Integration

The Fruit Ninja game doubles as the **primary ML training environment**:
- `L` key: Start recording gestures (learn mode)
- `T` key: Use trained model for cursor control (test mode)
- `G` key: Guided learn flow with directional prompts
- `V` key: Show cross-validation results panel

The `SmartRecorder` labels gestures by blade→fruit direction, making real
gameplay the training data source.
