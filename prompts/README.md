# Arcade for All — Implementation Prompts

This folder contains prompt files for each module of the project. Use them to:
- Revisit the design intent of each module
- Brief an AI assistant or new developer on a specific component
- Edit requirements before re-generating code

## Files

| File | Module | Description |
|------|--------|-------------|
| [00_concept.md](00_concept.md) | Whole project | Vision, goals, tech stack, how to run |
| [01_sensor.md](01_sensor.md) | `shared/sensor.py` | BLE IMU streaming via bleak |
| [02_gesture.md](02_gesture.md) | `shared/gesture.py` | Tilt/flick/spin → GestureState |
| [03_home_screen.md](03_home_screen.md) | `home.py` | Animated card-tile game selector |
| [04_game_bricks.md](04_game_bricks.md) | `games/bricks/game.py` | Breakout game with 5 levels |
| [05_game_snake.md](05_game_snake.md) | `games/snake/game.py` | Grid snake, 4-direction tilt control |
| [06_calibration_game.md](06_calibration_game.md) | `games/calibration/game.py` | Aviation-style pitch/roll/yaw visualizer |
| [07_audio.md](07_audio.md) | `shared/audio.py` | Background music + SFX manager |
| [08_main_orchestrator.md](08_main_orchestrator.md) | `main.py` | Entry point, wires all components |

## How to use a prompt

1. Open the relevant `.md` file
2. Edit requirements, thresholds, or visual design as needed
3. Paste the updated prompt to Claude (or another LLM) along with the current file contents
4. Review the generated changes against the rest of the codebase

## Component dependencies

```
main.py
 ├── shared/sensor.py   ← BLE thread
 ├── shared/gesture.py  ← gesture thread (consumes sensor.data_queue)
 ├── shared/audio.py    ← audio manager
 ├── home.py            ← selection screen (reads gesture thread)
 └── games/
     ├── bricks/game.py
     ├── snake/game.py
     └── calibration/game.py
```

All games share the same `GestureState` interface — swapping sensor for keyboard requires no game code changes.
