# Release 0.1 Implementation Tasks

## Phase 2 — Sensor Reliability
- [x] 2a. Fix double `_emit_sample()` in sensor.py (dirty-flag pair)
- [x] 2b. Replace `print()` with `logging` in sensor.py
- [x] 2b. Replace `print()` with `logging` in gesture.py
- [x] 2c. Add `sensor_disconnected` field to GestureState + track in `_loop()`

## Phase 3 — Calibration Game Dead Code Removal
- [ ] 3. Remove dead `_pf_*` / Pre-Flight methods from calibration/game.py
- [ ] 3. Add sensor status line to calibration view

## Phase 4 — Architecture Cleanup
- [x] 4c. Fix `get_state()` to use `replace(self.state)` in gesture.py
- [x] 4d. Replace `sys.exit(0)` → `return "quit"` in home.py
- [x] 4d. Replace `sys.exit(0)` → `return "quit"` in games/bricks/game.py
- [x] 4d. Replace `sys.exit(0)` → `return "quit"` in games/snake/game.py
- [x] 4d. Replace `sys.exit(0)` → `return "quit"` in games/fruit_ninja/game.py
- [x] 4d. Replace `sys.exit(0)` → `return "quit"` in games/magic_wand/game.py
- [x] 4d. Replace `sys.exit(0)` → `return "quit"` in games/calibration/game.py
- [x] 4d. Replace `sys.exit(0)` → `return "quit"` in shared/username_screen.py
- [x] 4b. Add GAME_REGISTRY + handle "quit" sentinel in main.py

## Phase 5 — Polish
- [x] Create shared/constants.py with BASE_W, BASE_H
- [x] M3. Cache PowerUp font in games/bricks/game.py
- [x] L4. Cap `_cal_buf` with deque(maxlen=...) in gesture.py
- [x] M2. Promote magic numbers to GestureConfig fields in gesture.py
- [x] L6. Remove dead `_DE` constant from shared/audio.py
- [ ] L3. Add GameResult enum (deferred — str sentinels work, enum is pure polish)
- [x] M7. Move rc_car_bridge.py / rc_simulator.py to examples/

## Phase 3 (deferred)
- [ ] Remove dead Pre-Flight methods from calibration/game.py (lower risk, separate PR)

## Verification
- [x] py_compile all 12 modified files → ALL OK
- [ ] pytest (pytest not installed in env; unittest runner shows pre-existing import error unrelated to our changes)
