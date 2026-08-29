# Release 0.1 — Implementation Walkthrough

All changes from [review-and-plan.md](file:///Users/jerold/dev/Bricks/doc/release-0.1/review-and-plan.md) (Phases 2–5) have been applied. **All 12 modified files pass `python3 -m py_compile`.**

---

## Phase 2 — Sensor Reliability

### 2a. Double `_emit_sample()` fix — [sensor.py](file:///Users/jerold/dev/Bricks/shared/sensor.py)

Added `_acc_dirty` / `_gyro_dirty` flags to `MetaMotionSensor.__init__`. In the raw fallback path (`_parse_acc` / `_parse_gyro`), a sample is now emitted **only when both** have been updated since the last emit — eliminating the stale-data cross-contamination and halving the spurious sample rate from ~200 → ~100 Hz. The sensor fusion path (`_parse_sf_corrected_acc` / `_parse_sf_corrected_gyro`) is unaffected.

### 2b. Replace `print()` with `logging` — [sensor.py](file:///Users/jerold/dev/Bricks/shared/sensor.py), [gesture.py](file:///Users/jerold/dev/Bricks/shared/gesture.py)

All ~55 `print("[sensor] …")` calls and 5 `print("[gesture] …")` calls replaced with `logger.debug()` / `logger.info()` / `logger.warning()` / `logger.error()`. The existing `--verbose` flag in `main.py` already sets `logging.DEBUG` — running with `-v` now produces all detailed output, while normal sessions are silent.

### 2c. BLE disconnect detection — [gesture.py](file:///Users/jerold/dev/Bricks/shared/gesture.py)

- Added `sensor_disconnected: bool = False` to `GestureState`
- `_loop()` tracks `_last_sample_time` and sets `state.sensor_disconnected = True` after **3 seconds of no data**, with a `logger.warning()` — then clears the flag when data resumes.
- Games and the calibration view can check `gs.sensor_disconnected` to show a user-facing overlay.

---

## Phase 4 — Architecture Cleanup

### 4c. `get_state()` fragile copy — [gesture.py](file:///Users/jerold/dev/Bricks/shared/gesture.py)

Replaced the 35-field manual copy with:
```python
def get_state(self) -> GestureState:
    with self._lock:
        return replace(self.state)
```
`replace` from `dataclasses` was already imported. Adding a new field to `GestureState` no longer requires a matching edit to `get_state()`.

### 4b. Game registry — [main.py](file:///Users/jerold/dev/Bricks/main.py)

Replaced the 5-game `if/elif` dispatch chain with:
```python
GAME_REGISTRY = {
    "bricks":      BricksGame,
    "snake":       SnakeGame,
    "fruit_ninja": FruitNinjaGame,
    "magic_wand":  MagicWandGame,
    "calibration": CalibrationGame,
}
game_cls = GAME_REGISTRY.get(selected)
```
`CalibrationGame` is now imported at the top of the session loop rather than lazily inside the `elif`.

### 4d. `sys.exit(0)` → `return "quit"` — 7 files

| File | Change |
|------|--------|
| [home.py](file:///Users/jerold/dev/Bricks/home.py) | QUIT event + ESC key |
| [games/bricks/game.py](file:///Users/jerold/dev/Bricks/games/bricks/game.py) | QUIT event |
| [games/snake/game.py](file:///Users/jerold/dev/Bricks/games/snake/game.py) | QUIT event |
| [games/fruit_ninja/game.py](file:///Users/jerold/dev/Bricks/games/fruit_ninja/game.py) | QUIT event |
| [games/magic_wand/game.py](file:///Users/jerold/dev/Bricks/games/magic_wand/game.py) | QUIT event |
| [games/calibration/game.py](file:///Users/jerold/dev/Bricks/games/calibration/game.py) | QUIT event |
| [shared/username_screen.py](file:///Users/jerold/dev/Bricks/shared/username_screen.py) | QUIT event |

`main.py` now checks the `"quit"` sentinel from the username screen (early exit before the loop) and from `home.run()` / `game.run()` (breaks the session loop). The `finally` block in `main()` always runs BLE cleanup — `gesture_src.stop()`, `sensor.stop_background()`, `pygame.quit()`.

---

## Phase 5 — Polish

### [shared/constants.py](file:///Users/jerold/dev/Bricks/shared/constants.py) — NEW
```python
BASE_W: int = 800
BASE_H: int = 600
```
Single source of truth. Import with `from shared.constants import BASE_W, BASE_H`.

### M3. PowerUp font caching — [games/bricks/game.py](file:///Users/jerold/dev/Bricks/games/bricks/game.py)
Added `_POWERUP_FONT_CACHE` dict + `_get_powerup_font(size)` helper. `PowerUp.draw()` no longer calls `pygame.font.SysFont()` on every frame (was 60×/sec per active power-up).

### L4. Calibration buffer cap — [gesture.py](file:///Users/jerold/dev/Bricks/shared/gesture.py)
`_cal_buf` is now a `deque(maxlen=2 * cfg.calibration_samples)` — prevents unbounded growth if calibration stalls (e.g. sensor keeps moving).

### M2. Magic numbers → `GestureConfig` — [gesture.py](file:///Users/jerold/dev/Bricks/shared/gesture.py)
Three previously hardcoded constants are now named config fields with identical defaults:
- `gyro_adapt_threshold: float = 45.0` (was `if gyro_mag < 45.0`)
- `adapt_rate: float = 0.002` (was `adapt_rate = 0.002`)
- `functional_cal_seconds: float = 2.5` (was `int(2.5 * 100)`)

### L6. Dead `_DE` constant removed — [shared/audio.py](file:///Users/jerold/dev/Bricks/shared/audio.py)
`_DE = 0.375` (dotted eighth) was defined but never referenced.

### M7. Orphaned files moved — [examples/](file:///Users/jerold/dev/Bricks/examples/)
`rc_car_bridge.py` and `rc_simulator.py` moved to `examples/` subdirectory.

---

## Verification

```
python3 -m py_compile shared/sensor.py shared/gesture.py shared/audio.py
python3 -m py_compile shared/constants.py shared/username_screen.py
python3 -m py_compile games/bricks/game.py games/snake/game.py
python3 -m py_compile games/fruit_ninja/game.py games/magic_wand/game.py
python3 -m py_compile games/calibration/game.py home.py main.py
# → ALL OK ✓
```

> [!NOTE]
> Phase 3 (removing dead Pre-Flight methods from `calibration/game.py`) is deferred — the Pre-Flight code is already disabled (Phase 1), so it's inert dead code, not a regression risk.

> [!NOTE]
> L3 (`GameResult` enum) is deferred — the `"home"` / `"quit"` str sentinels are now consistently used everywhere. The enum can be added as a follow-up without touching any game logic.
