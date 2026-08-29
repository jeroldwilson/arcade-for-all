# Arcade for All — Release 0.1 Implementation Plan

Implementing all actionable phases from [review-and-plan.md](file:///Users/jerold/dev/Bricks/doc/release-0.1/review-and-plan.md) (Phase 2 through Phase 5). Phase 1 (sensor fusion mode + Pre-Flight disable) is already complete.

---

## Proposed Changes

### Phase 2 — Sensor Reliability

---

#### [MODIFY] [sensor.py](file:///Users/jerold/dev/Bricks/shared/sensor.py)

**2a. Fix double `_emit_sample()` in raw fallback mode**

Add `_acc_dirty` / `_gyro_dirty` flags to `__init__`. In `_parse_acc()` and `_parse_gyro()`, set the dirty flag and only call `_emit_sample()` when *both* are set, then clear both.

**2b. Replace `print()` with `logging`**

- All ~50 `print(f"[sensor] …")` calls → `logger.debug()` or `logger.info()` as appropriate:
  - Connection/disconnect/scan events → `logger.info()`
  - GATT service enumeration, per-sample prints, heartbeat prints → `logger.debug()`
  - Errors → `logger.error()`

---

#### [MODIFY] [gesture.py](file:///Users/jerold/dev/Bricks/shared/gesture.py)

**2b. Replace `print()` with `logging`**

- `print("[gesture] Calibrated…")` → `logger.info()`
- `print("[gesture] tilt=…")` per-sample print → `logger.debug()`
- `print("[gesture] Recalibration started…")` → `logger.info()`
- `print("[gesture] Functional calibration…")` → `logger.info()`
- `print("[gesture] PCA …")` → `logger.info()`

**2c. BLE disconnect detection**

Track consecutive `queue.Empty` timeouts in `_loop()`. After ~3 seconds of no data, set `state.sensor_disconnected = True` (new field on `GestureState`). Reset to `False` on next received sample.

Add `sensor_disconnected: bool = False` to `GestureState`.

---

#### [MODIFY] [main.py](file:///Users/jerold/dev/Bricks/main.py)

**2b. Wire `--verbose` flag to logging** (already present in `parse_args` but not yet linked to sensor/gesture loggers — verify it works for all child modules).

---

### Phase 3 — Calibration Game Dead Code Removal

---

#### [MODIFY] [calibration/game.py](file:///Users/jerold/dev/Bricks/games/calibration/game.py)

Remove all dead Pre-Flight code left over from Phase 1 disable:
- Delete `_draw_pre_flight_overlay()`, `_draw_signal_gauge()`, `_draw_takeoff_animation()` methods
- Delete all `_pf_*` instance variables from `__init__`
- Delete `_update_pre_flight()` no-op method
- Add a simple status line in the calibration view showing sensor mode and connection status using `gs.sensor_disconnected`

---

### Phase 4 — Architecture Cleanup

---

#### [MODIFY] [gesture.py](file:///Users/jerold/dev/Bricks/shared/gesture.py)

**4c. Fix `get_state()` fragile copy**

Replace the 35-field manual copy with `replace(self.state)` (dataclasses `replace` is already imported):

```python
def get_state(self) -> GestureState:
    with self._lock:
        return replace(self.state)
```

---

#### [MODIFY] [home.py](file:///Users/jerold/dev/Bricks/home.py)

**4d. Replace `sys.exit(0)` with return sentinel**

Replace all `pygame.quit(); sys.exit(0)` → `return "quit"`. The main loop already handles `"quit"` check (we add it in main.py).

---

#### [MODIFY] [main.py](file:///Users/jerold/dev/Bricks/main.py)

**4b. Game registry** — replace the 5 copy-pasted `if/elif` blocks:

```python
GAME_REGISTRY = {
    "bricks":      BricksGame,
    "snake":       SnakeGame,
    "fruit_ninja": FruitNinjaGame,
    "magic_wand":  MagicWandGame,
    "calibration": CalibrationGame,
}
```

**4d. Handle `"quit"` sentinel** from home screen and games — break out of the session loop and let the `finally` block run cleanup.

---

#### [MODIFY] [games/bricks/game.py](file:///Users/jerold/dev/Bricks/games/bricks/game.py)

**4d** + **M3**: Replace `sys.exit(0)` with `return "quit"`. Cache PowerUp font at init instead of creating it on every `draw()` call.

---

#### [MODIFY] [games/snake/game.py](file:///Users/jerold/dev/Bricks/games/snake/game.py)

**4d**: Replace `sys.exit(0)` with `return "quit"`.

---

#### [MODIFY] [games/fruit_ninja/game.py](file:///Users/jerold/dev/Bricks/games/fruit_ninja/game.py)

**4d**: Replace `pygame.quit(); sys.exit(0)` with `return "quit"`.

---

#### [MODIFY] [games/magic_wand/game.py](file:///Users/jerold/dev/Bricks/games/magic_wand/game.py)

**4d**: Replace `sys.exit(0)` with `return "quit"`.

---

#### [MODIFY] [games/calibration/game.py](file:///Users/jerold/dev/Bricks/games/calibration/game.py)

**4d**: Replace `sys.exit(0)` with `return "quit"`.

---

#### [MODIFY] [shared/username_screen.py](file:///Users/jerold/dev/Bricks/shared/username_screen.py)

**4d**: Replace `sys.exit(0)` with `return "quit"` — `main.py` will detect this and exit cleanly.

---

### Phase 5 — Polish & Testing

---

#### [NEW] [shared/constants.py](file:///Users/jerold/dev/Bricks/shared/constants.py)

```python
BASE_W, BASE_H = 800, 600
```

Update all game files and home.py to import from here instead of redefining locally.

---

#### [MODIFY] [games/bricks/game.py](file:///Users/jerold/dev/Bricks/games/bricks/game.py)

**M3. PowerUp font caching** — add a `_POWERUP_FONT` module-level cached font (initialized lazily) so `PowerUp.draw()` doesn't call `pygame.font.SysFont()` 60×/sec.

---

#### [MODIFY] [shared/gesture.py](file:///Users/jerold/dev/Bricks/shared/gesture.py)

**L4. Cap `_cal_buf`** — change `self._cal_buf: List[tuple] = []` to use a `deque(maxlen=2 * cfg.calibration_samples)` so it can't grow unbounded.

**M2. Move magic numbers to `GestureConfig`** — promote `45.0` (gyro threshold for adaptation gating), `0.002` (adapt_rate), and `int(2.5 * 100)` (functional cal samples) to named `GestureConfig` fields with defaults.

---

#### [MODIFY] [shared/audio.py](file:///Users/jerold/dev/Bricks/shared/audio.py)

**L6. Remove dead `_DE` constant**.

---

#### [MODIFY] [main.py](file:///Users/jerold/dev/Bricks/main.py) + relevant game files

**L3. `GameResult` enum** — add `class GameResult(str, Enum): HOME = "home"; QUIT = "quit"` to a shared location (or inline in main.py) so return values are typed, not bare strings.

---

#### Orphaned file moves (M7)

Move `rc_car_bridge.py` and `rc_simulator.py` to `examples/`.

---

## Verification Plan

### Automated
```bash
cd /Users/jerold/dev/Bricks
python3 -m py_compile shared/sensor.py shared/gesture.py shared/audio.py shared/constants.py
python3 -m py_compile games/bricks/game.py games/snake/game.py games/fruit_ninja/game.py
python3 -m py_compile games/magic_wand/game.py games/calibration/game.py
python3 -m py_compile home.py main.py shared/username_screen.py
python3 -m pytest tests/ -v
```

### Manual
- Run `python main.py --keyboard` — confirm game launches, home navigation works, ESC returns home, Q/window-close exits cleanly (no BLE leak)
- Run `python main.py --keyboard --verbose` — confirm debug output flows through `logging.DEBUG` in sensor/gesture modules
