"""
main.py — Entry point for MetaMotion Arcade

Usage
─────
  # Show home screen, then play selected game
  python main.py

  # Connect to a known device address (skips scan)
  python main.py --address D5:4A:AA:11:22:33

  # Keyboard-only mode (no sensor required — great for testing)
  python main.py --keyboard

  # Debug HUD (sensor values shown on-screen)
  python main.py --debug

  # List nearby BLE devices and exit
  python main.py --scan

  # Fullscreen
  python main.py --fullscreen

Architecture
────────────
  MetaMotionSensor          (shared/sensor.py)   — BLE thread
       │ data_queue (IMUSample)
       ▼
  GestureInterpreter        (shared/gesture.py)  — gesture thread
       │ get_state() → GestureState
       ▼
  HomeScreen.run()          (home.py)            — game selection menu
       │ returns game name
       ▼
  BricksGame / SnakeGame    (games/*/game.py)    — main/pygame thread
"""

import argparse
import asyncio
import logging
import sys
import time

import pygame

# ── Optional: pretty colour logging ──────────────────────────────────────────
try:
    import colorlog
    handler = colorlog.StreamHandler()
    handler.setFormatter(colorlog.ColoredFormatter(
        "%(log_color)s%(levelname)-8s%(reset)s %(message)s"
    ))
    logging.basicConfig(handlers=[handler], level=logging.WARNING)
except ImportError:
    logging.basicConfig(
        format="%(levelname)-8s %(message)s",
        level=logging.WARNING,
    )

logger = logging.getLogger(__name__)


# ── Argument parsing ──────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="MetaMotion Arcade — control games with wrist gestures"
    )
    p.add_argument(
        "--address", metavar="ADDR",
        help="BLE address of the MetaMotion device (skip scan)"
    )
    p.add_argument(
        "--keyboard", action="store_true",
        help="Use keyboard instead of sensor (arrow keys + SPACE)"
    )
    p.add_argument(
        "--scan", action="store_true",
        help="Scan for nearby BLE devices, print them, then exit"
    )
    p.add_argument(
        "--debug", action="store_true",
        help="Show sensor debug HUD in game (also toggled with D key)"
    )
    p.add_argument(
        "--fullscreen", action="store_true",
        help="Run in fullscreen mode"
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging"
    )
    return p.parse_args()


# ── BLE scan-only mode ────────────────────────────────────────────────────────

async def _scan_and_print(timeout: float = 10.0) -> None:
    """Scan for BLE devices and print any MetaWear/MetaMotion ones."""
    from bleak import BleakScanner
    print(f"Scanning for BLE devices ({timeout:.0f}s)…\n")
    results = await BleakScanner.discover(timeout=timeout, return_adv=True)
    if not results:
        print("No BLE devices found.")
        return

    mm_found = []
    others   = []
    for d, adv in results.values():
        name = d.name or "<unknown>"
        if any(k in name for k in ("MetaWear", "MetaMotion", "MWC", "MMS")):
            mm_found.append((d, adv))
        else:
            others.append((d, adv))

    if mm_found:
        print("MetaMotion / MetaWear devices:")
        for d, adv in mm_found:
            print(f"  ✓  {d.name:<30} {d.address}  rssi={adv.rssi} dBm")
    else:
        print("No MetaMotion device found.")

    print(f"\nAll other BLE devices ({len(others)}):")
    for d, _ in others[:20]:
        print(f"       {(d.name or '<unnamed>'):<30} {d.address}")


# ── Splash screen ─────────────────────────────────────────────────────────────

SPLASH = r"""
  ██████╗ ██████╗ ██╗ ██████╗██╗  ██╗███████╗
  ██╔══██╗██╔══██╗██║██╔════╝██║ ██╔╝██╔════╝
  ██████╔╝██████╔╝██║██║     █████╔╝ ███████╗
  ██╔══██╗██╔══██╗██║██║     ██╔═██╗ ╚════██║
  ██████╔╝██║  ██║██║╚██████╗██║  ██╗███████║
  ╚═════╝ ╚═╝  ╚═╝╚═╝ ╚═════╝╚═╝  ╚═╝╚══════╝

     MetaMotion Wrist-Gesture Arcade
"""

def _print_splash(mode: str) -> None:
    print(SPLASH)
    print(f"  Mode   : {mode}")
    print()

def _print_controls() -> None:
    print("  Sensor controls:")
    print("    Tilt wrist LEFT / RIGHT  →  move / navigate")
    print("    Tilt wrist FORWARD/BACK  →  up / down (Snake)")
    print("    Flick wrist UP           →  launch ball / select game")
    print("    Rotate wrist CW/CCW      →  ball spin / curve (Bricks)")
    print()
    print("  Keyboard shortcuts (always available):")
    print("    ← / →          move paddle / navigate cards")
    print("    ↑ / ↓          Snake direction")
    print("    SPACE          launch ball")
    print("    ESC            pause / back to menu")
    print("    R              restart (after game over)")
    print("    D              toggle debug HUD")
    print("    F              toggle fullscreen")
    print()


# ── Gesture source factory ────────────────────────────────────────────────────

def _build_gesture_source(args: argparse.Namespace):
    """Build and start the appropriate gesture source. Returns (gesture_src, sensor)."""
    if args.keyboard:
        from shared.gesture import KeyboardFallback
        gs = KeyboardFallback()
        gs.start()
        _print_splash("KEYBOARD")
        _print_controls()
        return gs, None

    from shared.sensor  import MetaMotionSensor
    from shared.gesture import GestureInterpreter, GestureConfig

    _print_splash("MetaMotion SENSOR")
    _print_controls()

    sensor = MetaMotionSensor(scan_timeout=12)
    print("[main] Starting sensor…  (make sure Bluetooth is on)")
    try:
        sensor.start_background(address=args.address)
    except RuntimeError as exc:
        print(f"\n[main] Could not connect to sensor: {exc}")
        print("[main] Falling back to keyboard mode.\n")
        from shared.gesture import KeyboardFallback
        gs = KeyboardFallback()
        gs.start()
        return gs, None

    cfg = GestureConfig()
    gs  = GestureInterpreter(sensor.data_queue, cfg)
    gs.start()
    print("[main] Gesture interpreter started.")
    return gs, sensor


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Scan-only mode — no pygame needed
    if args.scan:
        asyncio.run(_scan_and_print())
        sys.exit(0)

    # ── Initialize pygame once (owned here for the full session) ──────────
    pygame.init()
    flags  = pygame.FULLSCREEN if args.fullscreen else 0
    screen = pygame.display.set_mode((800, 600), flags)
    pygame.display.set_caption("MetaMotion Arcade")
    clock  = pygame.time.Clock()

    # ── Build gesture source once (sensor + interpreter live for the session)
    gesture_src, sensor = _build_gesture_source(args)

    # ── Main selection loop ────────────────────────────────────────────────
    from home import HomeScreen
    from games.bricks.game import BricksGame
    from games.snake.game  import SnakeGame

    home = HomeScreen(screen, clock)

    try:
        while True:
            selected = home.run(gesture_src)

            if selected == "bricks":
                game = BricksGame(screen, clock, debug=args.debug)
                game.run(gesture_src)   # returns "home"

            elif selected == "snake":
                game = SnakeGame(screen, clock, debug=args.debug)
                game.run(gesture_src)   # returns "home"

    except KeyboardInterrupt:
        print("\n[main] Interrupted.")
    finally:
        print("[main] Shutting down…")
        gesture_src.stop()
        if sensor is not None:
            sensor.stop_background()
        pygame.quit()
        print("[main] Done.")


if __name__ == "__main__":
    main()
