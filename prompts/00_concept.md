# Arcade for All — Concept & Goals

## What is it?
A Python + pygame arcade game suite controlled by wrist gestures from a MbientLab MetaMotion wrist-worn IMU sensor. The project is designed for **accessibility** — it works equally well with wrist gestures (sensor), keyboard, or mouse.

## Core Vision
- Anyone can play, regardless of motor ability or experience level
- Two modes: **ASTRA** (accessible — forgiving, slower, wider paddle) and **VEERA** (standard — full speed)
- Graceful fallback: if no sensor is detected, the game silently switches to keyboard mode

## Target Users
- Rehabilitation / physiotherapy patients using wrist movement as exercise
- Gamers who want novel motion controls
- Developers evaluating BLE IMU integration

## Project Goals
1. Demonstrate real-time BLE IMU → game control pipeline with sub-100ms latency
2. Provide two accessibility tiers in every game
3. Clean, readable Python codebase — no C extensions, no native SDK required
4. Single command to run: `python main.py`

## Non-Goals
- Not a mobile app
- Not multiplayer
- Not a full game engine (pygame is the engine)

## Key Design Decisions
- `pygame.init()` and `display.set_mode()` are owned by `main.py` only — game classes receive the surface
- All games share a single `GestureState` interface — sensor and keyboard look identical to game code
- Accessible mode is opt-in at the CLI (`--mode accessible`) but is the default when a sensor is connected
- No install step beyond `pip install -r requirements.txt`

## Tech Stack
| Layer | Technology |
|-------|-----------|
| Language | Python 3.10+ |
| Game engine | pygame 2.5+ |
| BLE | bleak 0.21+ (no native SDK) |
| Signal processing | numpy (optional, currently unused in core) |
| Sensor | MbientLab MetaMotion S/R, BMI160 IMU |
| IMU config | ±4g accel @ 100Hz, ±500°/s gyro @ 100Hz |

## Running the project
```bash
source .venv/bin/activate

# Keyboard mode (no sensor)
python main.py --keyboard

# Auto-scan for sensor (accessible/ASTRA mode by default)
python main.py

# Standard/VEERA mode with sensor
python main.py --mode standard

# Debug HUD
python main.py --debug
```
