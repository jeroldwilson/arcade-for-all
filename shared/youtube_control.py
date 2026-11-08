"""
shared/youtube_control.py — Accessible Wrist-Gesture YouTube TV Controller & Server

Provides:
  1. Per-user channel/playlist JSON storage (`data/youtube_channels_{username}.json`)
     with zero API tokens required and URL parsing for YouTube videos & playlists.
  2. Deliberate 3-Step Combo Gesture Lock (`YouTubeGestureController`) so excited
     hand movements while watching never accidentally change the video:
     - Step 1 (WAKE / UNLOCK): Upward Wrist Flick (`gs.launch`) OR holding wrist
       tilted for 0.9s unlocks the remote for 6 seconds.
     - Step 2 (RETURN TO CENTER): Relax wrist back to neutral (`|tilt| < 0.35`)
       so a single continuous spasm cannot complete both steps at once.
     - Step 3 (DELIBERATE SWIPE / HOLD LEFT or RIGHT): Hold or swipe Left/Right
       to confirm Previous / Next Video.
  3. Browser-to-Pygame ESC / Quit Bridge (`/api/quit`) so pressing ESC or clicking
     "Back to Arcade" inside the browser window cleanly exits back to the Pygame
     Home Screen and brings the Pygame window to the front.
  4. Native Browser Control (`NativeBrowserBridge`) via macOS `osascript`.
"""

import json
import logging
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from shared.gesture_engine import GestureEngineManager
from shared.gesture_learner import PROFILE_ACCESSIBLE, PROFILE_STANDARD

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DEFAULT_CONFIG_PATH = DATA_DIR / "youtube_channels.json"
DECK_HTML_PATH = Path(__file__).resolve().parent / "youtube_deck.html"


# ── Non-blocking TTS Helper ───────────────────────────────────────────────────

class YouTubeTTS:
    """Non-blocking macOS `say` / Linux `espeak` voice feedback for TV couch viewing."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._say_bin = shutil.which("say")
        self._espeak_bin = shutil.which("espeak") or shutil.which("espeak-ng")

    def speak(self, text: str, interrupt: bool = True, rate: int = 185) -> None:
        if not self.enabled or not text or not (self._say_bin or self._espeak_bin):
            return

        def _worker():
            with self._lock:
                if interrupt and self._proc is not None:
                    try:
                        if self._proc.poll() is None:
                            self._proc.terminate()
                    except Exception:
                        pass
                    self._proc = None
                try:
                    if self._say_bin:
                        self._proc = subprocess.Popen(
                            [self._say_bin, "-r", str(rate), text],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                    elif self._espeak_bin:
                        self._proc = subprocess.Popen(
                            [self._espeak_bin, "-s", str(rate), text],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                except Exception:
                    self._proc = None

        threading.Thread(target=_worker, daemon=True).start()

    def stop(self) -> None:
        with self._lock:
            if self._proc is not None:
                try:
                    if self._proc.poll() is None:
                        self._proc.terminate()
                except Exception:
                    pass
                self._proc = None


# ── URL Parser & Per-User Channel Config ──────────────────────────────────────

def parse_youtube_url(url_or_id: str) -> Tuple[str, str]:
    """
    Extract (video_id, playlist_id) from any YouTube watch URL, short URL,
    playlist URL, or raw 11-char video ID. No API token needed.
    """
    raw = (url_or_id or "").strip()
    if not raw:
        return "", ""

    if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
        return raw, ""

    if re.fullmatch(r"[A-Za-z0-9_-]{13,42}", raw) and not raw.startswith("http"):
        return "", raw

    try:
        parsed = urllib.parse.urlparse(raw)
        qs = urllib.parse.parse_qs(parsed.query)
        video_id = qs.get("v", [""])[0]
        playlist_id = qs.get("list", [""])[0]

        if not video_id and "youtu.be" in parsed.netloc:
            video_id = parsed.path.lstrip("/").split("/")[0]
        elif not video_id and "/shorts/" in parsed.path:
            video_id = parsed.path.split("/shorts/")[1].split("/")[0]
        elif not video_id and "/embed/" in parsed.path:
            video_id = parsed.path.split("/embed/")[1].split("/")[0]

        return video_id, playlist_id
    except Exception:
        return raw, ""


def get_user_channels_path(username: str = "") -> Path:
    """Return the per-user channel config path, initializing from default if needed."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    safe_user = re.sub(r"[^a-zA-Z0-9_-]", "", (username or "").strip().lower())
    if not safe_user or safe_user == "guest":
        target = DEFAULT_CONFIG_PATH
    else:
        target = DATA_DIR / f"youtube_channels_{safe_user}.json"

    if not target.exists():
        if DEFAULT_CONFIG_PATH.exists():
            target.write_text(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            default_data = {
                "settings": {
                    "cooldown_seconds": 5.0,
                    "tilt_hold_seconds": 0.9,
                    "tilt_threshold": 0.65,
                    "require_combo": True,
                    "combo_window_seconds": 6.0,
                    "allow_flick_pause": False,
                    "tts_enabled": True,
                },
                "channels": [
                    {
                        "id": "music_beats",
                        "name": "Channel 1: Teen Music & Electronic Beats (NCS)",
                        "accent": "#00E5FF",
                        "items": [
                            {
                                "title": "Cartoon — On & On (Electronic Pop)",
                                "video_id": "K4DyBUG242c",
                                "playlist_id": "",
                            }
                        ],
                    }
                ],
            }
            target.write_text(json.dumps(default_data, indent=2), encoding="utf-8")
    return target


def focus_pygame_window() -> None:
    """Bring the Python/Pygame Arcade window back to the foreground on macOS."""
    osascript = shutil.which("osascript")
    if not osascript:
        return

    def _worker():
        try:
            script = (
                'tell application "System Events" to set frontmost of '
                '(first process whose unix id is ' + str(subprocess.os.getpid()) + ') to true'
            )
            subprocess.run(
                [osascript, "-e", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1.5,
            )
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True).start()


# ── Native Browser Bridge (macOS AppleScript) ─────────────────────────────────

class NativeBrowserBridge:
    """
    Controls an active logged-in YouTube / YouTube Shorts / YouTube TV tab
    in Google Chrome or Safari on macOS without requiring any API tokens.
    """

    def __init__(self, submode: str = "playlist"):
        self.submode = submode  # "playlist" or "shorts"
        self._osascript = shutil.which("osascript")

    def send_command(self, action: str) -> None:
        if not self._osascript:
            return
        threading.Thread(target=self._run_apple_script, args=(action,), daemon=True).start()

    def _run_apple_script(self, action: str) -> None:
        try:
            if self.submode == "shorts":
                key_code = 125 if action == "next" else (126 if action == "prev" else 49)
                script = f'tell application "System Events" to key code {key_code}'
            else:
                if action == "next":
                    script = 'tell application "System Events" to keystroke "N" using {shift down}'
                elif action == "prev":
                    script = 'tell application "System Events" to keystroke "P" using {shift down}'
                elif action == "toggle_pause":
                    script = 'tell application "System Events" to keystroke "k"'
                else:
                    return
            subprocess.run(
                [self._osascript, "-e", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1.5,
            )
        except Exception as exc:
            logger.debug("NativeBrowserBridge osascript error: %s", exc)


# ── Core Accessible Gesture-to-YouTube State Machine ──────────────────────────

class YouTubeGestureController:
    """
    Processes GestureState frames into deliberate 3-step combo YouTube navigation
    events so excited hand movements while watching never accidentally skip videos:

      Step 0 (WATCH LOCK):
        - Kid can wave, laugh, or move freely. Single spikes are ignored.
        - To unlock: Either perform an UPWARD FLICK (`gs.launch`) OR hold wrist
          steadily tilted for `tilt_hold_required` (0.9s).
      Step 1 (RETURN TO NEUTRAL):
        - Once unlocked, wrist must briefly pass through neutral (`|tilt| < 0.35`)
          so a single continuous posture doesn't auto-fire Step 2.
      Step 2 (ARMED — SWIPE OR HOLD LEFT/RIGHT WITHIN 6s):
        - Now a clear Left or Right swipe/hold changes the video!
    """

    def __init__(
        self,
        username: str = "",
        mode: str = "accessible",
        native_browser: bool = False,
        browser_submode: str = "playlist",
        require_combo: Optional[bool] = None,
    ):
        self.username = username or "Guest"
        self.mode = mode
        self.native_browser = native_browser
        self._browser_bridge = NativeBrowserBridge(submode=browser_submode)
        self._lock = threading.Lock()

        self.config_path = get_user_channels_path(self.username)
        self._data: Dict[str, Any] = {}
        self.channels: List[Dict[str, Any]] = []
        self.reload_config()

        settings = self._data.get("settings", {})
        self.cooldown_duration: float = float(settings.get("cooldown_seconds", 5.0))
        self.tilt_hold_required: float = float(settings.get("tilt_hold_seconds", 0.9))
        self.tilt_threshold: float = float(settings.get("tilt_threshold", 0.65))
        self.require_combo: bool = (
            bool(settings.get("require_combo", True))
            if require_combo is None
            else require_combo
        )
        self.combo_window_duration: float = float(settings.get("combo_window_seconds", 6.0))
        self.allow_flick_pause: bool = bool(settings.get("allow_flick_pause", False))
        self.tts = YouTubeTTS(enabled=bool(settings.get("tts_enabled", True)))

        # Personalized ML Gesture Engine
        profile = PROFILE_ACCESSIBLE if mode == "accessible" else PROFILE_STANDARD
        self.learner = GestureEngineManager(username=self.username, profile=profile)

        # Navigation indices
        self.channel_idx: int = 0
        self.item_idx: int = 0

        # 3-Step Combo State:
        #   0 = LOCKED (Watching safely)
        #   1 = UNLOCKED, WAITING FOR NEUTRAL CENTER
        #   2 = ARMED & READY FOR LEFT/RIGHT SWIPE
        self.combo_step: int = 0
        self.combo_timer: float = 0.0
        self.unlock_charge: float = 0.0

        # Live HUD state
        self.tilt: float = 0.0
        self.calibrated: bool = False
        self.left_charge: float = 0.0
        self.right_charge: float = 0.0
        self.cooldown_rem: float = 0.0
        self.last_command: str = ""
        self.last_command_time: float = 0.0
        self.command_seq: int = 0

        # Flag set when user presses ESC or "Back to Arcade" in the Web Deck
        self.quit_requested: bool = False

    def request_quit(self) -> None:
        """Signal the Pygame loop to exit YouTube TV and return to HomeScreen."""
        self.quit_requested = True
        focus_pygame_window()

    def reload_config(self) -> None:
        with self._lock:
            try:
                self._data = json.loads(self.config_path.read_text(encoding="utf-8"))
                self.channels = self._data.get("channels", [])
            except Exception as exc:
                logger.warning("Failed to read %s: %s", self.config_path, exc)
                self.channels = []
            if not self.channels:
                self.channels = [
                    {
                        "id": "default",
                        "name": "Channel 1: Teen Music & Electronic Beats (NCS)",
                        "accent": "#00E5FF",
                        "items": [
                            {
                                "title": "Cartoon — On & On (Electronic Pop)",
                                "video_id": "K4DyBUG242c",
                                "playlist_id": "",
                            }
                        ],
                    }
                ]
            settings = self._data.get("settings", {})
            self.cooldown_duration = float(settings.get("cooldown_seconds", 5.0))
            self.tilt_hold_required = float(settings.get("tilt_hold_seconds", 0.9))
            self.tilt_threshold = float(settings.get("tilt_threshold", 0.65))
            self.combo_window_duration = float(settings.get("combo_window_seconds", 6.0))

    def save_config(self) -> None:
        with self._lock:
            self._data["channels"] = self.channels
            self.config_path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def refresh_default_channels(self) -> None:
        """Reset this user's channel list from the latest default `youtube_channels.json`."""
        if DEFAULT_CONFIG_PATH.exists():
            self.config_path.write_text(
                DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8"
            )
            self.reload_config()
            self.channel_idx = 0
            self.item_idx = 0
            self.command_seq += 1
            self.last_command = "refresh"

    def add_video(self, channel_name: str, title: str, url: str) -> bool:
        vid_id, pl_id = parse_youtube_url(url)
        if not vid_id and not pl_id:
            return False

        with self._lock:
            target_ch = None
            for ch in self.channels:
                if ch.get("name", "").strip().lower() == channel_name.strip().lower():
                    target_ch = ch
                    break
            if target_ch is None:
                target_ch = {
                    "id": re.sub(r"[^a-z0-9_]", "_", channel_name.lower()),
                    "name": channel_name,
                    "accent": "#00E5FF",
                    "items": [],
                }
                self.channels.append(target_ch)

            target_ch["items"].append(
                {
                    "title": title or f"Video ({vid_id or pl_id})",
                    "video_id": vid_id,
                    "playlist_id": pl_id,
                }
            )
        self.save_config()
        return True

    def delete_video(self, channel_idx: int, item_idx: int) -> bool:
        with self._lock:
            if 0 <= channel_idx < len(self.channels):
                items = self.channels[channel_idx].get("items", [])
                if 0 <= item_idx < len(items) and len(items) > 1:
                    items.pop(item_idx)
                    self.item_idx = 0
                else:
                    return False
            else:
                return False
        self.save_config()
        return True

    @property
    def current_channel(self) -> Dict[str, Any]:
        with self._lock:
            if not self.channels:
                return {"name": "Channel 1", "accent": "#00E5FF", "items": []}
            self.channel_idx %= len(self.channels)
            return self.channels[self.channel_idx]

    @property
    def current_item(self) -> Dict[str, Any]:
        ch = self.current_channel
        items = ch.get("items", [])
        if not items:
            return {"title": "No videos in channel", "video_id": "K4DyBUG242c", "playlist_id": ""}
        self.item_idx %= len(items)
        return items[self.item_idx]

    def _unlock_combo(self, already_neutral: bool = False) -> None:
        """Transition from Step 0 (Watch Lock) into Step 1 or Step 2."""
        self.combo_step = 2 if already_neutral else 1
        self.combo_timer = self.combo_window_duration
        self.unlock_charge = 0.0
        self.left_charge = 0.0
        self.right_charge = 0.0
        self.tts.speak("Ready. Swipe left or right.")

    def update(self, gs, dt: float) -> Optional[str]:
        """
        Process one frame of GestureState. Returns triggered action name
        ('next', 'prev', 'next_channel', 'toggle_pause') or None.
        """
        if self.cooldown_rem > 0.0:
            self.cooldown_rem = max(0.0, self.cooldown_rem - dt)

        # Update combo window timer
        if self.combo_step > 0:
            self.combo_timer = max(0.0, self.combo_timer - dt)
            if self.combo_timer <= 0.0:
                self.combo_step = 0
                self.left_charge = 0.0
                self.right_charge = 0.0

        if gs is None:
            return None

        self.calibrated = bool(getattr(gs, "calibrated", False))
        self.tilt = float(getattr(gs, "paddle_velocity", 0.0))

        # Feed ML gesture learner buffer
        if self.learner.model_ready:
            try:
                self.learner.update(gs)
            except Exception:
                pass

        # While in post-switch cooldown, keep everything locked
        if self.cooldown_rem > 0.0:
            self.combo_step = 0
            self.unlock_charge = 0.0
            self.left_charge = max(0.0, self.left_charge - dt * 3.0)
            self.right_charge = max(0.0, self.right_charge - dt * 3.0)
            return None

        # ── 3-STEP COMBO GUARD (Prevents accidental skips when excited) ────────
        if self.require_combo:
            if self.combo_step == 0:
                # Step 1: Must Unlock first!
                # Option A: Upward flick (`gs.launch`)
                if bool(getattr(gs, "launch", False)):
                    self._unlock_combo(already_neutral=(abs(self.tilt) < 0.35))
                    return None

                # Option B: Steady tilt hold for `tilt_hold_required` (0.9s)
                if abs(self.tilt) >= self.tilt_threshold:
                    self.unlock_charge = min(1.0, self.unlock_charge + dt / self.tilt_hold_required)
                    if self.unlock_charge >= 1.0:
                        self._unlock_combo(already_neutral=False)
                else:
                    self.unlock_charge = max(0.0, self.unlock_charge - dt * 2.5)
                return None

            elif self.combo_step == 1:
                # Step 2: Must relax wrist back to neutral center (`|tilt| < 0.35`)
                if abs(self.tilt) < 0.35:
                    self.combo_step = 2
                return None

        # ── STEP 3 (Or Direct Mode if require_combo=False): ARMED FOR SWIPE ────
        steer_right = bool(getattr(gs, "steer_right", False))
        steer_left = bool(getattr(gs, "steer_left", False))
        slice_active = bool(getattr(gs, "slice_active", False))
        slice_dir = str(getattr(gs, "slice_direction", ""))

        # Check ML prediction if user has a trained model
        ml_dir = ""
        if self.learner.model_ready and slice_active:
            try:
                pred_label, conf = self.learner.predict(gs)
                if pred_label and conf >= 0.60:
                    ml_dir = pred_label
            except Exception:
                pass

        if steer_right or (slice_active and slice_dir in ("right", "diagonal_ur", "diagonal_dr")) or ml_dir == "right":
            return self.trigger_action("next")

        if steer_left or (slice_active and slice_dir in ("left", "diagonal_ul", "diagonal_dl")) or ml_dir == "left":
            return self.trigger_action("prev")

        # Sustained wrist tilt hold (0.9s confirm hold)
        if self.tilt >= self.tilt_threshold:
            self.right_charge = min(1.0, self.right_charge + dt / self.tilt_hold_required)
            self.left_charge = max(0.0, self.left_charge - dt * 2.5)
            if self.right_charge >= 1.0:
                return self.trigger_action("next")
        elif self.tilt <= -self.tilt_threshold:
            self.left_charge = min(1.0, self.left_charge + dt / self.tilt_hold_required)
            self.right_charge = max(0.0, self.right_charge - dt * 2.5)
            if self.left_charge >= 1.0:
                return self.trigger_action("prev")
        else:
            self.left_charge = max(0.0, self.left_charge - dt * 2.2)
            self.right_charge = max(0.0, self.right_charge - dt * 2.2)

        if self.allow_flick_pause and not self.require_combo and bool(getattr(gs, "launch", False)):
            return self.trigger_action("toggle_pause")

        return None

    def trigger_action(self, action: str, apply_cooldown: bool = True) -> str:
        """Execute a navigation command ('next', 'prev', 'next_channel', 'prev_channel', 'toggle_pause', 'unlock')."""
        if action == "unlock":
            self._unlock_combo(already_neutral=True)
            return "unlock"

        with self._lock:
            ch = self.channels[self.channel_idx % len(self.channels)] if self.channels else {"items": []}
            items = ch.get("items", [])
            n_items = max(1, len(items))

            if action == "next":
                self.item_idx = (self.item_idx + 1) % n_items
            elif action == "prev":
                self.item_idx = (self.item_idx - 1) % n_items
            elif action == "next_channel":
                self.channel_idx = (self.channel_idx + 1) % max(1, len(self.channels))
                self.item_idx = 0
            elif action == "prev_channel":
                self.channel_idx = (self.channel_idx - 1) % max(1, len(self.channels))
                self.item_idx = 0

            # Re-lock combo and start cooldown
            self.combo_step = 0
            self.combo_timer = 0.0
            self.unlock_charge = 0.0
            self.left_charge = 0.0
            self.right_charge = 0.0
            if apply_cooldown:
                self.cooldown_rem = self.cooldown_duration
            self.last_command = action
            self.last_command_time = time.monotonic()
            self.command_seq += 1

        # Announce via TTS
        cur_item = self.current_item
        cur_ch = self.current_channel
        if action == "next":
            self.tts.speak(f"Next: {cur_item.get('title', 'Video')}")
        elif action == "prev":
            self.tts.speak(f"Previous: {cur_item.get('title', 'Video')}")
        elif action in ("next_channel", "prev_channel"):
            self.tts.speak(f"{cur_ch.get('name', 'Channel')}. {cur_item.get('title', '')}")
        elif action == "toggle_pause":
            self.tts.speak("Play Pause")

        # Forward to native browser if enabled
        if self.native_browser:
            self._browser_bridge.send_command(action)

        return action

    def get_snapshot(self) -> Dict[str, Any]:
        """Return JSON-serializable state for the HTML TV Deck and Pygame HUD."""
        ch = self.current_channel
        item = self.current_item
        return {
            "username": self.username,
            "config_file": f"data/{self.config_path.name}",
            "calibrated": self.calibrated,
            "ml_ready": self.learner.model_ready,
            "tilt": round(self.tilt, 3),
            "require_combo": self.require_combo,
            "combo_step": self.combo_step,
            "combo_timer": round(self.combo_timer, 1),
            "unlock_charge": round(self.unlock_charge, 3),
            "left_charge": round(self.left_charge, 3),
            "right_charge": round(self.right_charge, 3),
            "cooldown_rem": round(self.cooldown_rem, 2),
            "cooldown_frac": round(
                min(1.0, self.cooldown_rem / max(0.1, self.cooldown_duration)), 3
            ),
            "channel_idx": self.channel_idx,
            "channel_name": ch.get("name", "Channel 1"),
            "channel_accent": ch.get("accent", "#00E5FF"),
            "item_idx": self.item_idx,
            "current_item": item,
            "channels": self.channels,
            "last_command": self.last_command,
            "command_seq": self.command_seq,
            "quit_requested": self.quit_requested,
        }


# ── Background HTTP Server for the HTML5 YouTube Deck ─────────────────────────

class YouTubeDeckServer:
    """
    Lightweight local HTTP server that serves `shared/youtube_deck.html` and
    exposes REST endpoints so the browser player stays in sync with the sensor.
    """

    def __init__(self, controller: YouTubeGestureController, port: int = 8765):
        self.controller = controller
        self.port = port
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def start(self, open_browser: bool = True) -> str:
        ctrl = self.controller

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass  # Keep console clean during 20Hz polling

            def _send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
                raw = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:
                if self.path == "/" or self.path.startswith("/index"):
                    html_bytes = DECK_HTML_PATH.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(html_bytes)))
                    self.end_headers()
                    self.wfile.write(html_bytes)
                elif self.path.startswith("/api/state"):
                    self._send_json(ctrl.get_snapshot())
                else:
                    self.send_error(404)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
                try:
                    data = json.loads(body)
                except Exception:
                    data = {}

                if self.path.startswith("/api/action"):
                    act = data.get("action", "next")
                    ctrl.trigger_action(act)
                    self._send_json({"ok": True, "state": ctrl.get_snapshot()})
                elif self.path.startswith("/api/quit"):
                    ctrl.request_quit()
                    self._send_json({"ok": True})
                elif self.path.startswith("/api/refresh_defaults"):
                    ctrl.refresh_default_channels()
                    self._send_json({"ok": True, "state": ctrl.get_snapshot()})
                elif self.path.startswith("/api/add_video"):
                    ok = ctrl.add_video(
                        channel_name=data.get("channel_name", "My Channel"),
                        title=data.get("title", "Favorite Video"),
                        url=data.get("url", ""),
                    )
                    self._send_json({"ok": ok, "state": ctrl.get_snapshot()})
                elif self.path.startswith("/api/delete_video"):
                    ok = ctrl.delete_video(
                        channel_idx=int(data.get("channel_idx", 0)),
                        item_idx=int(data.get("item_idx", 0)),
                    )
                    self._send_json({"ok": ok, "state": ctrl.get_snapshot()})
                else:
                    self.send_error(404)

        for candidate in range(self.port, self.port + 15):
            try:
                ThreadingHTTPServer.allow_reuse_address = True
                self._httpd = ThreadingHTTPServer(("127.0.0.1", candidate), _Handler)
                self.port = candidate
                break
            except OSError:
                continue

        if self._httpd is None:
            raise RuntimeError("Could not bind local YouTube Deck HTTP server.")

        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True, name="yt-deck-http"
        )
        self._thread.start()

        if open_browser:
            webbrowser.open(self.url)
        return self.url

    def stop(self) -> None:
        self.controller.tts.stop()
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None
