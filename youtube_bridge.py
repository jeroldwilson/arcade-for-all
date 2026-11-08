"""
youtube_bridge.py — Standalone Accessible YouTube TV Wrist-Gesture Launcher

Can be run directly (`python youtube_bridge.py`) without going through the
Arcade Home Screen, or launched via the "YOUTUBE TV" card inside `main.py`.

Usage:
  # Default: Connect MetaMotion sensor + open 10-foot HDMI TV YouTube Deck
  python youtube_bridge.py --user arjun

  # Keyboard-only testing (no sensor required)
  python youtube_bridge.py --keyboard --user arjun

  # Native Browser Mode: Control an active logged-in Chrome/Safari YouTube tab
  python youtube_bridge.py --native-browser --submode playlist
  python youtube_bridge.py --native-browser --submode shorts
"""

import argparse
import sys
import pygame

from main import _build_gesture_source
from shared.audio import make_audio_manager
from games.youtube_tv.game import YouTubeTVGame


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="ASTRA Accessible YouTube TV Wrist-Gesture Controller"
    )
    p.add_argument("--address", metavar="ADDR", help="BLE address of MetaMotion sensor")
    p.add_argument("--keyboard", action="store_true", help="Test with keyboard arrows (no sensor)")
    p.add_argument(
        "--mode",
        choices=["keyboard", "standard", "accessible"],
        default=None,
        help="Control mode (default: accessible ASTRA)",
    )
    p.add_argument("--user", default="Guest", help="Kid/Teen profile username (loads data/youtube_channels_<user>.json)")
    p.add_argument(
        "--native-browser",
        action="store_true",
        help="Also send Next/Prev hotkeys to active Chrome/Safari YouTube tab via macOS osascript",
    )
    p.add_argument(
        "--submode",
        choices=["playlist", "shorts"],
        default="playlist",
        help="Native browser sub-mode: 'playlist' (Shift+N / Shift+P) or 'shorts' (Down / Up arrows)",
    )
    p.add_argument("--no-open-browser", action="store_true", help="Do not auto-open browser tab on start")
    p.add_argument("--fullscreen", action="store_true", help="Run Pygame HUD in fullscreen")
    p.add_argument("--debug", action="store_true", help="Show raw IMU debug overlay")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    mode = args.mode or ("keyboard" if args.keyboard else "accessible")

    pygame.mixer.pre_init(44100, -16, 2, 512)
    pygame.init()
    if args.fullscreen:
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    else:
        screen = pygame.display.set_mode((800, 600))
    pygame.display.set_caption(f"ASTRA YouTube TV — {args.user}")
    clock = pygame.time.Clock()

    gesture_src, sensor = _build_gesture_source(args, mode)
    audio = make_audio_manager()

    try:
        app = YouTubeTVGame(
            screen=screen,
            clock=clock,
            debug=args.debug,
            mode=mode,
            audio=audio,
            username=args.user,
            open_browser_on_start=not args.no_open_browser,
            native_browser=args.native_browser,
            browser_submode=args.submode,
        )
        app.run(gesture_src)
    except KeyboardInterrupt:
        pass
    finally:
        gesture_src.stop()
        if sensor is not None:
            sensor.stop_background()
        pygame.quit()


if __name__ == "__main__":
    main()

