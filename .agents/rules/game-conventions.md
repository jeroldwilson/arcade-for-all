# Game Conventions & Coding Standards

## Game Constructor Pattern

Every game class MUST accept this constructor signature:

```python
class MyGame:
    def __init__(self, screen, clock, debug=False, mode="standard",
                 audio=None, username="", game_submode=None):
        self._screen = screen          # pygame.Surface (owned by main.py)
        self._clock = clock            # pygame.time.Clock (owned by main.py)
        self._debug = debug            # bool, toggled with D key
        self._mode = mode              # "standard" | "accessible"
        self._audio = audio            # AudioManager or _NullAudio (can be None)
        self._username = username      # str, player profile name
        self._game_submode = game_submode
        self.hud = GestureHUD(scale=0.3)  # REQUIRED — all games show gesture HUD
```

The `run(gesture_src)` method MUST:
- Accept a gesture source (GestureInterpreter or KeyboardGestureSource)
- Return `"home"` to go back to menu, or `"quit"` to exit entirely
- Preserve `self._debug` state (synced back to main.py after return)

## Shared Module API Contracts

### AudioManager (shared/audio.py)

Available methods (also on `_NullAudio` silent fallback):
- `start_background()` / `stop_background()` / `pause_background()` / `resume_background()`
- `play_collect()` — rising 3-note chime
- `play_hit()` — flick cast sound
- `play_game_over()` — fanfare
- `play_flick_cast()` — whoosh + sparkle
- `play_complete_fanfare()` — triumphant C-E-G-C6
- `play_encourage(username)` / `play_success(username)` — voice clips
- `play(sound_name)` — generic dispatcher ("powerup", "brick_hit", "fanfare", etc.)
- `update()` — call each frame to manage voice channel state

Always guard audio calls: `if self._audio: self._audio.play_collect()`

### VisualEffects (shared/game_experience.py)

Constructor: `VisualEffects(sensor=None)` — do NOT pass audio or username.

### InactivityMonitor (shared/game_experience.py)

Constructor: `InactivityMonitor(username, sensor=None, audio=None)` — positional args, no `screen` or `clock`.

### FireworksCelebration (shared/game_experience.py)

Constructor: `FireworksCelebration(W, H, username, score)` — screen dimensions + player info.

## Threading Model

1. **Main/pygame thread** — event loop, rendering, game logic (60 FPS)
2. **BLE thread** — asyncio event loop for bleak BLE I/O (sensor.py)
3. **Gesture thread** — drains sensor queue, runs Madgwick + gesture extraction (gesture.py)
4. **Validation thread** — background cross-validation (gesture_learner.py)

Cross-thread communication is ONLY via:
- `queue.Queue` (sensor → gesture)
- `get_state()` returns a snapshot copy (gesture → game)
- Never share mutable pygame surfaces or state across threads

## Resolution Independence

All games use `sc = min(W/800, H/600)` for scaling:
```python
self._W, self._H = screen.get_size()
self._sc = min(self._W / 800.0, self._H / 600.0)
```

## Pygame Color Safety

Any randomized RGB calculation MUST be clamped:
```python
color = tuple(max(0, min(255, c + random.randint(-20, 60))) for c in base_color)
```
Unclamped values crash `pygame.draw.circle()` with `ValueError: invalid color`.

## Game Mode Naming

- `"standard"` or `"veera"` → normal gameplay difficulty
- `"accessible"` or `"astra"` → accommodations for motor disabilities
- The `mode` string is passed in the constructor and used throughout

## Debug HUD

- Toggled with `D` key in any game or home screen
- Shows raw sensor values via `draw_gesture_debug_overlay()`
- State stored in `self._debug` and synced back to `main.py`

## Keyboard Fallback

All games must work with keyboard-only (no sensor):
- `KeyboardGestureSource` emits `GestureState` from arrow keys + spacebar
- Mouse can be used as cursor in Fruit Ninja
- Never assume `gesture_src` has BLE-specific attributes

## File Organization

```
games/{game_name}/
├── __init__.py     # Empty or re-export
└── game.py         # Single file containing the game class
```

Keep game logic in a single `game.py` file. Shared utilities go in `shared/`.
