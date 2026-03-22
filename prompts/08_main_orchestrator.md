# Prompt: Main Orchestrator (`main.py`)

## Task
Implement the entry point that owns pygame initialisation, parses CLI arguments, builds the gesture source, and runs the game selection loop. No game logic lives here — it only wires components together.

## CLI arguments
```
python main.py [options]

Options:
  --address ADDR     BLE address of MetaMotion device (skip scan)
  --keyboard         Use keyboard mode (alias for --mode keyboard)
  --mode MODE        keyboard | standard | accessible (default: accessible with sensor)
  --scan             Scan for nearby BLE devices and exit
  --debug            Show sensor debug HUD in game (also toggled with D key)
  --fullscreen       Start in fullscreen mode
  --verbose, -v      Enable DEBUG logging
```

## Mode resolution
```python
def _resolve_mode(args) -> str:
    if args.mode is not None: return args.mode
    if args.keyboard:          return "keyboard"
    return "accessible"   # default when sensor is used
```

## Startup sequence
```python
def main():
    args = parse_args()

    # Scan-only mode (no pygame)
    if args.scan:
        asyncio.run(_scan_and_print())
        sys.exit(0)

    # pygame init — owned here for entire session
    pygame.mixer.pre_init(44100, -16, 2, 512)
    pygame.init()
    if args.fullscreen:
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    else:
        screen = pygame.display.set_mode((800, 600))
    pygame.display.set_caption("Arcade for All")
    clock = pygame.time.Clock()

    # Gesture source
    mode = _resolve_mode(args)
    gesture_src, sensor = _build_gesture_source(args, mode)

    # Audio
    from shared.audio import make_audio_manager
    audio = make_audio_manager()

    # Game loop
    from home import HomeScreen
    from games.bricks.game import BricksGame
    from games.snake.game  import SnakeGame

    home = HomeScreen(screen, clock, mode=mode)

    try:
        while True:
            # Re-init layout if window was resized
            cur = pygame.display.get_surface()
            if cur.get_size() != home._layout_size:
                home._init_layout(cur)

            selected = home.run(gesture_src)
            mode = home.mode   # may have been toggled on home screen

            cur = pygame.display.get_surface()

            if selected == "bricks":
                BricksGame(cur, clock, debug=args.debug, mode=mode, audio=audio).run(gesture_src)
            elif selected == "snake":
                SnakeGame(cur, clock, debug=args.debug, mode=mode, audio=audio).run(gesture_src)
            elif selected == "calibration":
                from games.calibration.game import CalibrationGame
                CalibrationGame(cur, clock, debug=args.debug, mode=mode, audio=audio).run(gesture_src)

    except KeyboardInterrupt:
        print("\n[main] Interrupted.")
    finally:
        gesture_src.stop()
        if sensor: sensor.stop_background()
        pygame.quit()
```

## Gesture source factory
```python
def _build_gesture_source(args, mode):
    if mode == "keyboard":
        from shared.gesture import KeyboardFallback
        gs = KeyboardFallback(); gs.start()
        return gs, None

    from shared.sensor  import MetaMotionSensor
    from shared.gesture import GestureInterpreter, GestureConfig

    sensor = MetaMotionSensor(scan_timeout=12)
    try:
        sensor.start_background(address=args.address)
    except RuntimeError as exc:
        print(f"[main] Sensor failed: {exc}. Falling back to keyboard.")
        from shared.gesture import KeyboardFallback
        gs = KeyboardFallback(); gs.start()
        return gs, None

    gs = GestureInterpreter(sensor.data_queue, GestureConfig())
    gs.start()
    return gs, sensor
```

## BLE scan helper
```python
async def _scan_and_print(timeout=10.0):
    from bleak import BleakScanner
    results = await BleakScanner.discover(timeout=timeout, return_adv=True)
    mm_found = [(d, adv) for d, adv in results.values()
                if any(k in (d.name or "") for k in ("MetaWear","MetaMotion","MWC","MMS"))]
    # Print MetaMotion devices, then first 20 others
```

## Splash banner (terminal)
```
  █████╗ ██████╗  ██████╗ █████╗ ██████╗ ███████╗
 ██╔══██╗██╔══██╗██╔════╝██╔══██╗██╔══██╗██╔════╝
 ███████║██████╔╝██║     ███████║██║  ██║█████╗
 ██╔══██║██╔══██╗██║     ██╔══██║██║  ██║██╔══╝
 ██║  ██║██║  ██║╚██████╗██║  ██║██████╔╝███████╗
 ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚═════╝╚══════╝
          F  O  R     A  L  L

  Mode   : MetaMotion SENSOR  [ASTRA]
```
Followed by controls reference printed to stdout.

## Key invariants
- `pygame.init()` called **exactly once** here — never inside game classes
- `display.set_mode()` called here; games receive the live surface via `pygame.display.get_surface()`
- `gesture_src` and `sensor` are shut down in `finally` block regardless of how the loop exits
- All game imports are lazy (inside the loop) to keep startup fast
